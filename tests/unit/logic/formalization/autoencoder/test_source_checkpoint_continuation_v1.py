"""Saved-weight continuation contract controls, using synthetic inert backends.

These controls neither import numerical/package owners nor train or infer a
model. Their generated checkpoint and cached rows are portable contract fixtures,
not retained corpus evidence or evidence of numerical checkpoint consumption.
"""
from copy import deepcopy
import hashlib
import importlib.abc
import importlib.util
import json
from pathlib import Path
import sys

import pytest


_SOURCE = Path(__file__).resolve().parents[5] / "ipfs_datasets_py/logic/formalization/autoencoder/source_checkpoint_continuation_v1.py"
_SPEC = importlib.util.spec_from_file_location("detached_source_continuation_controls", _SOURCE)
subject = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(subject)

FALSE = ("qualified", "admitted", "proof_authority", "source_semantics_verified", "publication_performed")


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(raw(value)).hexdigest()


def manifest(rows):
    return [{"id": row["id"], "source_sha256": hashlib.sha256(row["source_text"].encode()).hexdigest(),
             "normalized_source_sha256": hashlib.sha256(" ".join(row["source_text"].casefold().split()).encode()).hexdigest(),
             "embedding_sha256": digest(row["embedding"]), "target_sha256": digest(row["target"])} for row in rows]


def tokens(value):
    if type(value) is dict:
        result = ["{"]
        for index, key in enumerate(sorted(value)):
            result.extend(([","] if index else []) + [raw(key).decode(), ":"] + tokens(value[key]))
        return result + ["}"]
    if type(value) is list:
        result = ["["]
        for index, child in enumerate(value):
            result.extend(([","] if index else []) + tokens(child))
        return result + ["]"]
    return [raw(value).decode()]


def target(index):
    return {"rules": [{"modality": ("O", "F")[index % 2], "actor": ("agency", "auditor")[index % 2],
                       "action": "save", "object": "report", "conditions": [], "exceptions": [], "temporal": []}]}


def rows(split):
    return [{"id": f"{split}-{index}", "source_text": f"Synthetic {split} source {index}.",
             "embedding": [(index + (1 if split == "fit" else 4)) / 10] + [0.] * 383,
             "target": target(index)} for index in range(2)]


def observation(exact=0):
    return {"objective": 1., "token_cross_entropy": 1., "weighted_cross_entropy": 1., "embedding_mse": .1,
            "exact_targets": exact, "valid_candidates": 2, "count": 2,
            "semantic_leaf_correct": exact * 2, "semantic_leaf_count": 4, "semantic_leaf_accuracy": exact / 2,
            "teacher_forcing_for_selection": True, "free_running_metrics_teacher_forced": False,
            "teacher_forcing_selection_role": "tertiary_tiebreaker"}


@pytest.fixture
def bundle(tmp_path):
    fit, validation = rows("fit"), rows("validation")
    vocabulary = ["<pad>", "<bos>", "<eos>", *sorted({token for row in fit for token in tokens(row["target"])})]
    count = len(vocabulary)
    shapes = {
        "projection_down.weight": (1, 384), "projection_down.bias": (1,),
        "projection_up.weight": (384, 1), "projection_up.bias": (384,),
        "condition.weight": (8, 384), "condition.bias": (8,),
        "target_embedding.weight": (count, 8), "decoder.weight_ih_l0": (24, 8),
        "decoder.weight_hh_l0": (24, 8), "decoder.bias_ih_l0": (24,),
        "decoder.bias_hh_l0": (24,), "output.weight": (count, 8), "output.bias": (count,),
    }
    # Every tensor has a different sentinel and every row has distinguishable
    # values, so partial restoration or lexical remapping changes the digest.
    def tensor(shape, base):
        return [tensor(shape[1:], base + index / 10000) for index in range(shape[0])] if shape else base
    weights = {name: tensor(shape, (index + 1) / 100) for index, (name, shape) in enumerate(shapes.items())}
    config = {"strategy": "semantic_v2", "epochs": 5, "max_seconds": 10., "learning_rate": .003,
              "batch_size": 2, "seed": 1729, "patience": 0, "max_optimizer_steps": 5,
              "reconstruction_weight": .1, "max_target_tokens": 192, "validation_interval": 1,
              "semantic_weight": 4., "constant_weight": 1., "structure_weight": .25,
              "input_normalization": "center_rms",
              "embedding_provenance": {"model_id": "synthetic-fixture", "verified_by_runtime": False},
              "hidden_size": 8, "token_embedding_dim": 8, "projection_width": 1}
    names = sorted(weights)
    lexical = ["output.bias", "output.weight", "target_embedding.weight"]
    checkpoint = {"schema": "shared-source-384-autoencoder/v2", "domain_id": "legal_ir", "dimension": 384,
                  "architecture": "residual-projection-latent-formula-gru/v1",
                  "codec": {"schema": "typed-json-lexical/v1", "target_vocabulary": vocabulary},
                  "config": config,
                  "implementation": {"runtime_sha256": "a" * 64, "legal_codec_sha256": "b" * 64,
                      "native": {"runtime": "c" * 64, "dependencies": {"synthetic.native.owner": "d" * 64},
                                 "scope": "listed_numerical_and_native_validator_modules_only"},
                      "numerical": {"files": {"synthetic.py": "e" * 64},
                                    "scope": "listed_latent_decoder_and_grammar_sources_only"}},
                  "parent_sha256": "f" * 64,
                  "parent_binding": {"domain": "legal_ir", "lineage_id": "current_legal_v2", "dimension": 384,
                                     "runtime_profile": "synthetic-parent/v1", "core_sha256": "1" * 64},
                  "lineage": {"exact_inherited_tensors": [name for name in names if name not in lexical],
                              "lexical_mapped_tensors": lexical, "new_token_initialization": "trained_parent_lexical_row_mean",
                              "random_parameters_used": False, "parent_modified": False,
                              "initial_state_sha256": digest(weights)},
                  "model_state": weights, "weights_sha256": digest(weights),
                  "input_transform": {"mode": "center_rms", "mean": [.25] + [0.] * 383,
                                      "scale": .5, "origin": "training_only"},
                  "semantic_paths": [["rules", 0, "actor"], ["rules", 0, "modality"]],
                  "training_manifest": manifest(fit), "validation_manifest": manifest(validation),
                  "training": {"optimizer_steps": 5, "selected_optimizer_steps": 3, "selected_epoch": 3,
                               "before_validation": observation(), "selected_validation": observation(1),
                               "test_used_for_selection": False}, **{name: False for name in FALSE}}
    path = tmp_path / "checkpoint.json"
    state = {"checkpoint": checkpoint, "path": path, "fit": fit, "validation": validation, "shapes": shapes}
    def repin():
        payload = raw(checkpoint)
        path.write_bytes(payload)
        state["pin"] = {"path": str(path), "sha256": hashlib.sha256(payload).hexdigest()}
    state["repin"] = repin
    repin()
    return state


def prepare(bundle, **options):
    return subject.prepare("legal_ir", bundle["fit"], bundle["validation"], source_checkpoint=bundle["pin"], **options)


def metrics():
    return {"optimizer_steps": 1, "selected_optimizer_steps": 0, "selected_epoch": 0,
            "before_validation": observation(1), "selected_validation": observation(1),
            "test_used_for_selection": False, "fresh_optimizer": True, "exact_optimizer_resume": False,
            "initial_optimizer_state_entries": 0}


def synthetic_backend(plan):
    checkpoint = deepcopy(plan["checkpoint"])
    checkpoint["config"] = deepcopy(plan["config"])
    checkpoint["training"] = metrics()
    return {"checkpoint": checkpoint, "metrics": metrics(),
            "initial_weights_sha256": digest(plan["checkpoint"]["model_state"]),
            "final_weights_sha256": digest(checkpoint["model_state"]),
            "numerical_owner_sha256": "2" * 64, "numerical_execution": False}


def warm(bundle, backend=synthetic_backend, **options):
    return subject.warm_start("legal_ir", bundle["fit"], bundle["validation"], source_checkpoint=bundle["pin"],
                              backend=backend, **options)


def test_prepare_retains_all_thirteen_tensors_and_decoder_coordinates(bundle):
    plan = prepare(bundle)
    expected = bundle["checkpoint"]
    assert plan["checkpoint"] == expected and plan["checkpoint"] is not expected
    assert set(plan["checkpoint"]["model_state"]) == set(bundle["shapes"])
    assert len(plan["checkpoint"]["model_state"]) == 13
    assert digest(plan["checkpoint"]["model_state"]) == expected["weights_sha256"]
    assert plan["config"] == expected["config"]
    assert plan["training_rows"] == bundle["fit"] and plan["validation_rows"] == bundle["validation"]
    assert plan["prior_selected_optimizer_steps"] == 3
    assert plan["checkpoint_pin"]["bytes"] == bundle["path"].stat().st_size


def test_preparation_is_detached_and_does_not_refit_transform_or_vocabulary(bundle):
    before = raw((bundle["checkpoint"], bundle["fit"], bundle["validation"]))
    plan = prepare(bundle)
    assert plan["checkpoint"]["input_transform"]["mean"][0] == .25
    assert plan["checkpoint"]["input_transform"]["scale"] == .5
    # Fit mean is .15, deliberately different from the saved mean.
    plan["checkpoint"]["input_transform"]["mean"][0] = 999
    plan["checkpoint"]["codec"]["target_vocabulary"][3] = "changed"
    plan["training_rows"][0]["embedding"][0] = 999
    assert raw((bundle["checkpoint"], bundle["fit"], bundle["validation"])) == before


def test_baseline_selection_preserves_saved_state_with_fresh_optimizer(bundle):
    before = bundle["path"].read_bytes(), raw((bundle["fit"], bundle["validation"]))
    calls = []
    def backend(plan):
        calls.append(plan)
        assert digest(plan["checkpoint"]["model_state"]) == bundle["checkpoint"]["weights_sha256"]
        return synthetic_backend(plan)
    result = warm(bundle, backend)
    assert len(calls) == 1 and result["schema"] == "source-checkpoint-continuation/v1"
    assert result["source_checkpoint"]["model_state"] == bundle["checkpoint"]["model_state"]
    assert result["training"]["optimizer_steps"] == 1
    assert result["training"]["selected_optimizer_steps"] == result["training"]["selected_epoch"] == 0
    assert result["training"]["fresh_optimizer"] is True
    assert result["training"]["exact_optimizer_resume"] is False
    assert result["training"]["initial_optimizer_state_entries"] == 0
    assert result["numerical_execution"] is False
    assert all(result[name] is False for name in FALSE)
    assert before == (bundle["path"].read_bytes(), raw((bundle["fit"], bundle["validation"])))


def test_valid_updated_state_is_retained_without_changing_saved_decoder_assets(bundle):
    def backend(plan):
        result = synthetic_backend(plan)
        result["checkpoint"]["model_state"]["output.bias"][0] += .01
        result["checkpoint"]["weights_sha256"] = digest(result["checkpoint"]["model_state"])
        result["final_weights_sha256"] = result["checkpoint"]["weights_sha256"]
        result["metrics"].update(selected_optimizer_steps=1, selected_epoch=1,
                                 selected_validation=observation(2))
        result["checkpoint"]["training"] = deepcopy(result["metrics"])
        return result
    result = warm(bundle, backend)
    updated = result["source_checkpoint"]
    assert updated["weights_sha256"] != bundle["checkpoint"]["weights_sha256"]
    assert updated["weights_sha256"] == digest(updated["model_state"])
    for name in bundle["shapes"]:
        if name != "output.bias":
            assert updated["model_state"][name] == bundle["checkpoint"]["model_state"][name]
    assert result["training"]["selected_epoch"] == result["training"]["selected_optimizer_steps"] == 1
    assert updated["codec"] == bundle["checkpoint"]["codec"]
    assert updated["input_transform"] == bundle["checkpoint"]["input_transform"]
    assert all(result[name] is False for name in FALSE)


def test_unknown_ir_schema_is_not_inferred_from_checkpoint_schema(bundle):
    result = warm(bundle)
    assert result["binding"] == {"ir_family_id": "legal_ir", "dimension": 384, "dimension_role": "input_embedding",
                                  "schema_version": None, "task_id": "typed_ir_reconstruction", "format_id": "semantic_json"}
    binding = {**result["binding"], "schema_version": "legal-semantic-json/v7"}
    with pytest.raises(ValueError, match="no authenticated IR schema binding"):
        warm(bundle, binding=binding)


@pytest.mark.parametrize("key,value", [("strategy", "reference_ce"), ("epochs", 2), ("max_seconds", 3.),
    ("learning_rate", .002), ("batch_size", 1), ("seed", 19), ("patience", 1), ("max_optimizer_steps", 1),
    ("reconstruction_weight", .2), ("validation_interval", 2), ("semantic_weight", 5.),
    ("constant_weight", 2.), ("structure_weight", .5)])
def test_optimization_overrides_preserve_frozen_assets(bundle, key, value):
    plan = prepare(bundle, config={key: value})
    assert plan["config"][key] == value
    assert plan["checkpoint"] == bundle["checkpoint"]
    for protected in ("max_target_tokens", "input_normalization", "embedding_provenance", "hidden_size",
                      "token_embedding_dim", "projection_width"):
        assert plan["config"][protected] == bundle["checkpoint"]["config"][protected]


@pytest.mark.parametrize("key", ["max_target_tokens", "input_normalization", "embedding_provenance", "hidden_size",
                                "token_embedding_dim", "projection_width"])
def test_protected_overrides_rejected_even_when_value_is_unchanged(bundle, key):
    with pytest.raises(ValueError):
        prepare(bundle, config={key: deepcopy(bundle["checkpoint"]["config"][key])})


@pytest.mark.parametrize("key,value", [("unknown", 1), ("epochs", True), ("epochs", 0),
    ("learning_rate", float("nan")), ("max_seconds", float("inf")), ("max_optimizer_steps", 0),
    ("batch_size", 257), ("strategy", "unrecognized")])
def test_invalid_optimization_options_fail_before_backend(bundle, key, value):
    def forbidden(plan):
        pytest.fail("backend called for rejected configuration")
    with pytest.raises(ValueError):
        warm(bundle, forbidden, config={key: value})


@pytest.mark.parametrize("key,value", [("ir_family_id", "intent_ir"), ("dimension", 8), ("dimension", 768),
    ("dimension", True), ("dimension_role", "latent"), ("task_id", "legal_text_reconstruction"),
    ("format_id", "fol"), ("schema_version", 7), ("schema_version", "")])
def test_family_dimension_schema_and_task_incompatibilities_rejected(bundle, key, value):
    binding = {"ir_family_id": "legal_ir", "dimension": 384, "dimension_role": "input_embedding",
               "schema_version": None, "task_id": "typed_ir_reconstruction", "format_id": "semantic_json"}
    binding[key] = value
    with pytest.raises(ValueError):
        prepare(bundle, binding=binding)


def test_closed_binding_rejects_omissions_and_additions(bundle):
    binding = prepare(bundle)["binding"]
    missing = {key: value for key, value in binding.items() if key != "schema_version"}
    for invalid in (missing, {**binding, "checkpoint_role": "student"}):
        with pytest.raises(ValueError):
            prepare(bundle, binding=invalid)


def test_other_requested_domain_rejected(bundle):
    with pytest.raises(ValueError):
        subject.prepare("intent_ir", bundle["fit"], bundle["validation"], source_checkpoint=bundle["pin"])


@pytest.mark.parametrize("split", ["fit", "validation"])
@pytest.mark.parametrize("failure", ["empty", "duplicate_id", "wrong_width", "nonfinite", "boolean_coordinate",
                                     "extra_field", "missing_target", "empty_source", "manifest_changed", "reordered"])
def test_invalid_or_changed_cached_split_rejected_before_backend(bundle, split, failure):
    data = bundle[split]
    if failure == "empty":
        data.clear()
    elif failure == "duplicate_id":
        data[1]["id"] = data[0]["id"]
    elif failure == "wrong_width":
        data[0]["embedding"].pop()
    elif failure == "nonfinite":
        data[0]["embedding"][0] = float("nan")
    elif failure == "boolean_coordinate":
        data[0]["embedding"][0] = True
    elif failure == "extra_field":
        data[0]["test_target"] = deepcopy(data[0]["target"])
    elif failure == "missing_target":
        del data[0]["target"]
    elif failure == "empty_source":
        data[0]["source_text"] = " \t"
    elif failure == "manifest_changed":
        data[0]["target"]["rules"][0]["actor"] = "different"
    else:
        data.reverse()
    def forbidden(plan):
        pytest.fail("backend called for invalid original cached split")
    with pytest.raises(ValueError):
        warm(bundle, forbidden)


@pytest.mark.parametrize("key", ["id", "source_text", "embedding"])
def test_overlap_rejected_even_when_checkpoint_manifests_are_resealed(bundle, key):
    bundle["validation"][0][key] = deepcopy(bundle["fit"][0][key])
    bundle["checkpoint"]["validation_manifest"] = manifest(bundle["validation"])
    bundle["repin"]()
    with pytest.raises(ValueError):
        prepare(bundle)


def test_casefold_whitespace_source_overlap_rejected(bundle):
    bundle["validation"][0]["source_text"] = "  " + bundle["fit"][0]["source_text"].upper().replace(" ", "\t") + "  "
    bundle["checkpoint"]["validation_manifest"] = manifest(bundle["validation"])
    bundle["repin"]()
    with pytest.raises(ValueError):
        prepare(bundle)


def test_unavailable_target_token_cannot_expand_saved_codec(bundle):
    bundle["fit"][0]["target"]["rules"][0]["actor"] = "unseen-person"
    bundle["checkpoint"]["training_manifest"] = manifest(bundle["fit"])
    bundle["repin"]()
    with pytest.raises(ValueError):
        prepare(bundle)


@pytest.mark.parametrize("failure", ["missing_tensor", "extra_tensor", "wrong_shape", "boolean_tensor",
    "stale_digest", "wrong_schema", "wrong_dimension", "wrong_architecture", "authority", "extra_checkpoint_field",
    "duplicate_vocabulary", "wrong_special_tokens", "wrong_transform_width", "bad_scale", "untrained"])
def test_malformed_checkpoint_rejected_without_backend(bundle, failure):
    checkpoint = bundle["checkpoint"]
    if failure == "missing_tensor":
        del checkpoint["model_state"]["condition.bias"]
    elif failure == "extra_tensor":
        checkpoint["model_state"]["unused.weight"] = [1.]
    elif failure == "wrong_shape":
        checkpoint["model_state"]["decoder.weight_hh_l0"][0].pop()
    elif failure == "boolean_tensor":
        checkpoint["model_state"]["output.bias"][0] = True
    elif failure == "stale_digest":
        checkpoint["model_state"]["output.bias"][0] += 1
    elif failure == "wrong_schema":
        checkpoint["schema"] = "domain-384-typed-autoencoder/v1"
    elif failure == "wrong_dimension":
        checkpoint["dimension"] = 768
    elif failure == "wrong_architecture":
        checkpoint["architecture"] = "unknown/v1"
    elif failure == "authority":
        checkpoint["qualified"] = True
    elif failure == "extra_checkpoint_field":
        checkpoint["optimizer_state"] = {}
    elif failure == "duplicate_vocabulary":
        checkpoint["codec"]["target_vocabulary"][4] = checkpoint["codec"]["target_vocabulary"][3]
    elif failure == "wrong_special_tokens":
        checkpoint["codec"]["target_vocabulary"][:3] = ["<eos>", "<bos>", "<pad>"]
    elif failure == "wrong_transform_width":
        checkpoint["input_transform"]["mean"].pop()
    elif failure == "bad_scale":
        checkpoint["input_transform"]["scale"] = 0
    else:
        checkpoint["training"]["optimizer_steps"] = 0
    if failure != "stale_digest":
        checkpoint["weights_sha256"] = digest(checkpoint["model_state"])
    bundle["repin"]()
    with pytest.raises(ValueError):
        prepare(bundle)


def test_checkpoint_byte_pin_and_regular_file_required(bundle, tmp_path):
    bundle["path"].write_bytes(bundle["path"].read_bytes() + b"\n")
    with pytest.raises(ValueError):
        prepare(bundle)
    bundle["repin"]()
    link = tmp_path / "checkpoint-link.json"
    link.symlink_to(bundle["path"])
    with pytest.raises(ValueError):
        subject.prepare("legal_ir", bundle["fit"], bundle["validation"],
                        source_checkpoint={"path": str(link), "sha256": bundle["pin"]["sha256"]})


def test_duplicate_json_keys_rejected_with_matching_byte_digest(bundle):
    payload = bundle["path"].read_bytes()
    payload = b'{"dimension":384,' + payload[1:]
    bundle["path"].write_bytes(payload)
    bundle["pin"]["sha256"] = hashlib.sha256(payload).hexdigest()
    with pytest.raises(ValueError):
        prepare(bundle)


@pytest.mark.parametrize("key,value", [("initial_weights_sha256", "0" * 64),
    ("final_weights_sha256", "0" * 64), ("numerical_owner_sha256", "invalid"),
    ("numerical_execution", "no"), ("numerical_execution", True)])
def test_untrusted_backend_receipt_rejected(bundle, key, value):
    def backend(plan):
        result = synthetic_backend(plan)
        result[key] = value
        return result
    with pytest.raises(ValueError):
        warm(bundle, backend)


@pytest.mark.parametrize("key,value", [("fresh_optimizer", False), ("exact_optimizer_resume", True),
    ("initial_optimizer_state_entries", 1), ("optimizer_steps", 0), ("optimizer_steps", True),
    ("selected_optimizer_steps", 2), ("selected_epoch", -1), ("test_used_for_selection", True)])
def test_backend_cannot_claim_resume_or_invalid_progress(bundle, key, value):
    def backend(plan):
        result = synthetic_backend(plan)
        result["metrics"][key] = value
        result["checkpoint"]["training"][key] = value
        return result
    with pytest.raises(ValueError):
        warm(bundle, backend)


@pytest.mark.parametrize("key", ["codec", "input_transform", "semantic_paths", "architecture", "implementation",
                                "parent_sha256", "parent_binding", "lineage", "training_manifest", "validation_manifest"])
def test_backend_cannot_replace_frozen_decoder_assets_or_native_provenance(bundle, key):
    def backend(plan):
        result = synthetic_backend(plan)
        result["checkpoint"][key] = None
        return result
    with pytest.raises(ValueError):
        warm(bundle, backend)


def test_backend_plan_mutation_cannot_hide_saved_codec_replacement(bundle):
    def backend(plan):
        plan["checkpoint"]["codec"]["target_vocabulary"][3] = '"corrupted"'
        return synthetic_backend(plan)
    with pytest.raises(ValueError):
        warm(bundle, backend)
    assert bundle["checkpoint"]["codec"]["target_vocabulary"][3] != '"corrupted"'


@pytest.mark.parametrize("key,value", [("count", 1), ("exact_targets", 3), ("valid_candidates", 0),
    ("semantic_leaf_count", 3), ("semantic_leaf_correct", 5), ("semantic_leaf_accuracy", 0.),
    ("objective", -1.), ("free_running_metrics_teacher_forced", True)])
def test_incomplete_or_inconsistent_free_running_observations_rejected(bundle, key, value):
    def backend(plan):
        result = synthetic_backend(plan)
        for name in ("before_validation", "selected_validation"):
            result["metrics"][name][key] = value
        result["checkpoint"]["training"] = deepcopy(result["metrics"])
        return result
    with pytest.raises(ValueError):
        warm(bundle, backend)


def test_selected_baseline_cannot_replace_saved_weights(bundle):
    def backend(plan):
        result = synthetic_backend(plan)
        result["checkpoint"]["model_state"]["output.bias"][0] += .01
        result["checkpoint"]["weights_sha256"] = digest(result["checkpoint"]["model_state"])
        result["final_weights_sha256"] = result["checkpoint"]["weights_sha256"]
        return result
    with pytest.raises(ValueError):
        warm(bundle, backend)


def test_semantic_selection_rejects_worse_generation_even_with_lower_token_loss(bundle):
    def backend(plan):
        result = synthetic_backend(plan)
        worse = observation(0)
        worse["objective"] = worse["token_cross_entropy"] = .01
        result["metrics"].update(selected_optimizer_steps=1, selected_epoch=1, selected_validation=worse)
        result["checkpoint"]["training"] = deepcopy(result["metrics"])
        return result
    with pytest.raises(ValueError):
        warm(bundle, backend)


def test_backend_metrics_and_checkpoint_training_must_agree(bundle):
    def backend(plan):
        result = synthetic_backend(plan)
        result["checkpoint"]["training"]["optimizer_steps"] = 2
        return result
    with pytest.raises(ValueError):
        warm(bundle, backend)


def test_backend_exception_preserves_original_inputs_and_checkpoint(bundle):
    before = bundle["path"].read_bytes(), raw((bundle["checkpoint"], bundle["fit"], bundle["validation"]))
    def backend(plan):
        plan["checkpoint"]["model_state"]["condition.bias"][0] = 999
        plan["training_rows"].clear()
        raise RuntimeError("inert backend failure")
    with pytest.raises(RuntimeError, match="inert backend failure"):
        warm(bundle, backend)
    assert before == (bundle["path"].read_bytes(), raw((bundle["checkpoint"], bundle["fit"], bundle["validation"])))


def fabricated_numeric_envelope(bundle):
    """Manufacture format metadata for an inert loader control, never evidence.

    No numerical owner executes. True here tests the serialized runtime-envelope
    branch only; an actual run requires separately authenticated execution.
    """
    envelope = warm(bundle)
    envelope["numerical_execution"] = True
    numeric_source = _SOURCE.with_name("source_checkpoint_continuation_numeric_v1.py")
    envelope["producer"]["numerical_owner_sha256"] = hashlib.sha256(numeric_source.read_bytes()).hexdigest()
    return envelope


def save_envelope(bundle, envelope):
    path = bundle["path"].with_name("synthetic-envelope.json")
    payload = raw(envelope)
    path.write_bytes(payload)
    return {"path": str(path), "sha256": hashlib.sha256(payload).hexdigest()}


def test_loader_passes_only_detached_legacy_payload_to_inert_runtime_loader(bundle):
    envelope = fabricated_numeric_envelope(bundle)
    reference = save_envelope(bundle, envelope)
    before = raw(envelope), Path(reference["path"]).read_bytes()
    marker = object()
    calls = []
    def loader(payload):
        calls.append(deepcopy(payload))
        assert payload["schema"] == "shared-source-384-autoencoder/v2"
        assert set(payload) == set(bundle["checkpoint"])
        assert digest(payload["model_state"]) == bundle["checkpoint"]["weights_sha256"]
        assert "producer" not in payload and "optimizer_state" not in payload
        payload["model_state"]["condition.bias"][0] = 999
        return marker
    result = subject.load_runtime(reference, expected_domain="legal_ir", expected_binding=envelope["binding"],
                                  runtime_loader=loader)
    assert result is marker and len(calls) == 1
    assert before == (raw(envelope), Path(reference["path"]).read_bytes())


@pytest.mark.parametrize("failure", ["non_numerical", "wrong_task", "nonnull_schema", "bad_owner_pin", "authority",
                                     "stale_weights", "lineage_weights", "metrics_mismatch",
                                     "fresh_optimizer", "invalid_observation", "changed_baseline"])
def test_invalid_runtime_envelope_rejected_before_loader(bundle, failure):
    envelope = fabricated_numeric_envelope(bundle)
    if failure == "non_numerical":
        envelope["numerical_execution"] = False
    elif failure == "wrong_task":
        envelope["binding"]["task_id"] = "legal_text_reconstruction"
    elif failure == "nonnull_schema":
        envelope["binding"]["schema_version"] = "unauthenticated-claim/v1"
    elif failure == "bad_owner_pin":
        envelope["producer"]["numerical_owner_sha256"] = "0" * 64
    elif failure == "authority":
        envelope["qualified"] = True
    elif failure == "stale_weights":
        envelope["source_checkpoint"]["model_state"]["output.bias"][0] += .01
    elif failure == "lineage_weights":
        envelope["lineage"]["selected_weights_sha256"] = "0" * 64
    elif failure == "metrics_mismatch":
        envelope["training"]["optimizer_steps"] = 2
    elif failure == "fresh_optimizer":
        envelope["training"]["fresh_optimizer"] = False
        envelope["source_checkpoint"]["training"] = deepcopy(envelope["training"])
    elif failure == "invalid_observation":
        for name in ("before_validation", "selected_validation"):
            envelope["training"][name]["count"] = 1
        envelope["source_checkpoint"]["training"] = deepcopy(envelope["training"])
    else:
        envelope["source_checkpoint"]["model_state"]["output.bias"][0] += .01
        envelope["source_checkpoint"]["weights_sha256"] = digest(envelope["source_checkpoint"]["model_state"])
        envelope["lineage"]["selected_weights_sha256"] = envelope["source_checkpoint"]["weights_sha256"]
    reference = save_envelope(bundle, envelope)
    def forbidden(payload):
        pytest.fail("inert runtime loader called for invalid envelope")
    with pytest.raises(ValueError):
        subject.load_runtime(reference, expected_domain="legal_ir", runtime_loader=forbidden)


def test_runtime_loader_rejects_other_family_and_expected_binding(bundle):
    envelope = fabricated_numeric_envelope(bundle)
    reference = save_envelope(bundle, envelope)
    for options in ({"expected_domain": "intent_ir"},
                    {"expected_domain": "legal_ir", "expected_binding": {**envelope["binding"], "dimension": 768}}):
        with pytest.raises(ValueError):
            subject.load_runtime(reference, runtime_loader=lambda payload: pytest.fail("incompatible loader called"),
                                 **options)


@pytest.mark.parametrize("failure", ["missing_lineage_field", "extra_lineage_field", "initial_weights",
    "prior_selected_steps", "prior_run_steps", "malformed_pin", "pin_byte_count", "donor_changed"])
def test_runtime_lineage_is_closed_and_bound_to_original_donor_before_loader(bundle, failure):
    envelope = fabricated_numeric_envelope(bundle)
    lineage = envelope["lineage"]
    if failure == "missing_lineage_field":
        del lineage["prior_selected_optimizer_steps"]
    elif failure == "extra_lineage_field":
        lineage["teacher_qualified"] = True
    elif failure == "initial_weights":
        lineage["initial_weights_sha256"] = "0" * 64
    elif failure == "prior_selected_steps":
        lineage["prior_selected_optimizer_steps"] += 1
    elif failure == "prior_run_steps":
        lineage["prior_run_optimizer_steps"] += 1
    elif failure == "malformed_pin":
        lineage["source_checkpoint_pin"]["sha256"] = "invalid"
    elif failure == "pin_byte_count":
        lineage["source_checkpoint_pin"]["bytes"] += 1
    else:
        bundle["path"].write_bytes(bundle["path"].read_bytes() + b"\n")
    reference = save_envelope(bundle, envelope)
    def forbidden(payload):
        pytest.fail("inert runtime loader called for unauthenticated donor lineage")
    with pytest.raises(ValueError):
        subject.load_runtime(reference, expected_domain="legal_ir", runtime_loader=forbidden)


@pytest.mark.parametrize("field", ["codec", "input_transform", "semantic_paths", "training_manifest",
                                   "implementation", "parent_binding", "config_shape"])
def test_runtime_frozen_assets_must_match_authenticated_donor(bundle, field):
    envelope = fabricated_numeric_envelope(bundle)
    checkpoint = envelope["source_checkpoint"]
    if field == "codec":
        vocabulary = checkpoint["codec"]["target_vocabulary"]
        vocabulary[3] = '"G"'
        vocabulary[3:] = sorted(vocabulary[3:])
    elif field == "input_transform":
        checkpoint["input_transform"]["mean"][0] += .01
    elif field == "semantic_paths":
        checkpoint["semantic_paths"].pop()
        for name in ("before_validation", "selected_validation"):
            envelope["training"][name].update(semantic_leaf_correct=1, semantic_leaf_count=2,
                                              semantic_leaf_accuracy=.5)
        checkpoint["training"] = deepcopy(envelope["training"])
    elif field == "training_manifest":
        checkpoint["training_manifest"][0]["id"] = "replacement-fit-row"
    elif field == "implementation":
        checkpoint["implementation"]["runtime_sha256"] = "0" * 64
    elif field == "parent_binding":
        checkpoint["parent_binding"]["runtime_profile"] = "replacement-parent/v1"
    else:
        # Make the new shape internally valid and give it improved selection;
        # only comparison with the authenticated saved donor can reject it.
        checkpoint["config"]["hidden_size"] = 9
        vocabulary_size = len(checkpoint["codec"]["target_vocabulary"])
        shapes = {"condition.weight": (9, 384), "condition.bias": (9,),
                  "decoder.weight_ih_l0": (27, 8), "decoder.weight_hh_l0": (27, 9),
                  "decoder.bias_ih_l0": (27,), "decoder.bias_hh_l0": (27,),
                  "output.weight": (vocabulary_size, 9)}
        def tensor(shape):
            return [tensor(shape[1:]) for _ in range(shape[0])] if shape else .125
        for name, shape in shapes.items():
            checkpoint["model_state"][name] = tensor(shape)
        checkpoint["weights_sha256"] = digest(checkpoint["model_state"])
        envelope["lineage"]["selected_weights_sha256"] = checkpoint["weights_sha256"]
        envelope["training"].update(selected_optimizer_steps=1, selected_epoch=1,
                                    selected_validation=observation(2))
        checkpoint["training"] = deepcopy(envelope["training"])
    reference = save_envelope(bundle, envelope)
    def forbidden(payload):
        pytest.fail("inert runtime loader called for replaced frozen donor assets")
    with pytest.raises(ValueError):
        subject.load_runtime(reference, expected_domain="legal_ir", runtime_loader=forbidden)


def test_parent_resolver_accepts_byte_identical_relocated_donor_and_gets_detached_pin(bundle):
    envelope = fabricated_numeric_envelope(bundle)
    copied = bundle["path"].with_name("relocated-donor.json")
    copied.write_bytes(bundle["path"].read_bytes())
    reference = save_envelope(bundle, envelope)
    before = raw(envelope)
    bundle["path"].unlink()
    marker = object()
    calls = []
    def resolver(recorded):
        calls.append(deepcopy(recorded))
        checksum = recorded["sha256"]
        recorded["path"] = "mutated-only-detached-argument"
        return {"path": str(copied), "sha256": checksum}
    assert subject.load_runtime(reference, expected_domain="legal_ir", parent_resolver=resolver,
                                runtime_loader=lambda payload: marker) is marker
    assert calls == [envelope["lineage"]["source_checkpoint_pin"]]
    assert raw(envelope) == before
    assert digest(envelope["source_checkpoint"]["model_state"]) == bundle["checkpoint"]["weights_sha256"]


def test_parent_resolver_cannot_substitute_different_hash(bundle):
    envelope = fabricated_numeric_envelope(bundle)
    reference = save_envelope(bundle, envelope)
    def forbidden(payload):
        pytest.fail("inert loader called after resolver substituted parent hash")
    with pytest.raises(ValueError):
        subject.load_runtime(reference, expected_domain="legal_ir", runtime_loader=forbidden,
                             parent_resolver=lambda recorded: {"path": str(bundle["path"]), "sha256": "0" * 64})


def test_resolver_cannot_bypass_malformed_recorded_parent_path(bundle):
    envelope = fabricated_numeric_envelope(bundle)
    envelope["lineage"]["source_checkpoint_pin"]["path"] = "relative-donor.json"
    reference = save_envelope(bundle, envelope)
    def forbidden_resolver(recorded):
        pytest.fail("resolver called before rejecting malformed recorded parent path")
    def forbidden_loader(payload):
        pytest.fail("loader called for malformed recorded parent path")
    with pytest.raises(ValueError):
        subject.load_runtime(reference, expected_domain="legal_ir", parent_resolver=forbidden_resolver,
                             runtime_loader=forbidden_loader)


def test_original_donor_change_during_inert_runtime_load_is_detected(bundle):
    envelope = fabricated_numeric_envelope(bundle)
    reference = save_envelope(bundle, envelope)
    def loader(payload):
        bundle["path"].write_bytes(bundle["path"].read_bytes() + b"\n")
        return object()
    with pytest.raises(ValueError):
        subject.load_runtime(reference, expected_domain="legal_ir", runtime_loader=loader)


def test_default_backend_contract_retains_legacy_runtime_payload_without_owner_execution(bundle, monkeypatch):
    numeric_source = _SOURCE.with_name("source_checkpoint_continuation_numeric_v1.py")
    owner_sha = hashlib.sha256(numeric_source.read_bytes()).hexdigest()
    calls = []
    class InertDefaultBackend:
        @staticmethod
        def run(plan):
            result = synthetic_backend(plan)
            # Manufactured execution metadata exercises the default API branch;
            # the substituted object is inert and provides no numeric evidence.
            result.update(numerical_execution=True, numerical_owner_sha256=owner_sha)
            return result
    def injected_import(name, package=None):
        assert name == ".source_checkpoint_continuation_numeric_v1"
        calls.append((name, package))
        return InertDefaultBackend
    monkeypatch.setattr(subject.importlib, "import_module", injected_import)
    result = subject.warm_start("legal_ir", bundle["fit"], bundle["validation"], source_checkpoint=bundle["pin"])
    assert len(calls) == 1
    assert result["source_checkpoint"]["schema"] == "shared-source-384-autoencoder/v2"
    assert result["source_checkpoint"]["model_state"] == bundle["checkpoint"]["model_state"]
    assert result["producer"]["numerical_owner_sha256"] == owner_sha
    assert all(result[name] is False for name in FALSE)


def test_detached_import_and_injected_path_never_load_numerical_or_package_owners(bundle):
    forbidden = ("torch", "numpy", "duckdb", "huggingface_hub", "ipfs_datasets_py", "ipfs_accelerate_py")
    class RefuseOwners(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.split(".")[0] in forbidden:
                raise AssertionError("unexpected owner import: " + fullname)
            return None
    guard = RefuseOwners()
    before = {name for name in sys.modules if name.split(".")[0] in forbidden}
    sys.meta_path.insert(0, guard)
    try:
        spec = importlib.util.spec_from_file_location("detached_source_continuation_import_control", _SOURCE)
        detached = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(detached)
        detached.warm_start("legal_ir", bundle["fit"], bundle["validation"], source_checkpoint=bundle["pin"],
                            backend=synthetic_backend)
    finally:
        sys.meta_path.remove(guard)
    assert {name for name in sys.modules if name.split(".")[0] in forbidden} == before
