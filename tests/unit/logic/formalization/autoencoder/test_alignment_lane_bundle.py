"""Synthetic identity-boundary attacks; no model output or semantic gold.

The fake producer artifact is deliberately unread. Its externally selected
content pins prevent local resealing from upgrading a substituted declaration.
"""
from __future__ import annotations

import builtins
import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import alignment_lane_bundle as subject


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(raw(value)).hexdigest()


def text_sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def seal(value):
    value["content_sha256"] = digest({key: item for key, item in value.items() if key != "content_sha256"})
    return value


def profile(lane="native384", stage="raw_embedding", *, dimension=None,
            recipe="exact_source_only/v1", precision=None, normalization=None):
    derived = stage in subject.DERIVED
    hidden = stage == "final_hidden_embedding"
    width = {"legacy8": 8, "native384": 384, "native768": 768, "leanstral": 4096}[lane]
    if dimension is not None:
        width = dimension
    method = "tensor_endpoint" if derived else "last_token" if hidden else {
        "legacy8": "none", "native384": "mean", "native768": "cls"}[lane]
    return seal({"schema": subject.PROFILE_SCHEMA, "lane_id": lane, "stage": stage, "dimension": width,
                 "producer": {"profile_id": "synthetic-unverified-producer/v1",
                              "model_id": "synthetic-no-model-was-loaded", "model_revision": "fixture-revision",
                              "code_sha256": "a" * 64, "model_assets_sha256": "b" * 64,
                              "checkpoint_sha256": "c" * 64 if derived or hidden else None},
                 "pooling": {"method": method, "endpoint": "synthetic/" + stage},
                 "normalization": normalization or {"kind": "none" if derived else "l2",
                                                       "unit_tolerance": None if derived else 1e-5},
                 "precision": precision or ("decimal6" if lane == "legacy8" and not derived else "float32"),
                 "fit_input_recipe": recipe, "inference_input_recipe": recipe})


def request(index, *, context_twins=False):
    source = "É📄 the clerk must retain evidence." if context_twins else f"É📄 clerk {index} must retain evidence."
    context_text = f"The declared record is shelf {index}." if context_twins else ""
    context = {"role": "declared_context" if context_twins else "none_required", "text": context_text,
               "bindings": {"record": {"kind": "literal", "value": f"shelf {index}"}} if context_twins else {},
               "sha256": text_sha(context_text)}
    return {"source_text": source, "context": context}


def encoder_text(value, recipe):
    if recipe == "exact_source_only/v1":
        return value["source_text"]
    forwarded = recipe == "role_marked_declared_context/v1"
    return raw({"schema": "role-marked-source-context/v1", "source": {"role": "source", "text": value["source_text"]},
                "assumptions": {"role": "declared_assumptions", "text": value["context"]["text"] if forwarded else "",
                                "bindings": value["context"]["bindings"] if forwarded else {}}}).decode("utf-8")


def row_binding(row):
    return {key: row[key] for key in subject.ROW_BINDING_FIELDS}


def refresh_input(row, recipe):
    row["input"]["context"]["sha256"] = text_sha(row["input"]["context"]["text"])
    row["input_sha256"] = digest(row["input"])
    row["encoder_text"] = encoder_text(row["input"], recipe)
    row["encoder_text_sha256"] = text_sha(row["encoder_text"])


def refresh_vector(row):
    row["vector_sha256"] = digest(row["vector"]) if row["vector"] is not None else None


def sync(bundle, *, producer_rows=True):
    """Rebuild local seals without changing any separately held expected pin."""
    seal(bundle["profile"])
    receipt = bundle["producer_receipt"]
    receipt["profile_sha256"] = digest(bundle["profile"])
    if producer_rows:
        receipt["rows"] = [row_binding(row) for row in bundle["rows"]]
        for row, bound in zip(bundle["rows"], receipt["rows"], strict=True):
            row["producer_row_sha256"] = digest(bound)
    seal(receipt)
    seal(bundle)
    return bundle


def expected(bundle):
    return {"profile_sha256": digest(bundle["profile"]),
            "producer_receipt_sha256": digest(bundle["producer_receipt"]),
            "inputs": [{"id": row["id"], "input_sha256": row["input_sha256"]} for row in bundle["rows"]]}


def case(lane="native384", stage="raw_embedding", *, dimension=None, recipe="exact_source_only/v1",
         context_twins=False, statuses=("available", "available"), precision=None, normalization=None):
    declared = profile(lane, stage, dimension=dimension, recipe=recipe, precision=precision,
                       normalization=normalization)
    rows = []
    for index, status in enumerate(statuses):
        vector = [0.0] * declared["dimension"]
        vector[index % len(vector)] = 1.0 if status == "available" else 0.0
        row = {"id": f"synthetic-unreviewed-{index}", "input": request(index, context_twins=context_twins),
               "status": status, "reason": None if status == "available" else "Explicit synthetic " + status,
               "vector": None if status == "unavailable" else vector,
               "upstream_vector_sha256": digest([float(index)]) if stage in subject.DERIVED else None,
               "token_receipt_sha256": None if lane == "legacy8" else digest({"synthetic_token_ids": [index, 2]}),
               "producer_row_sha256": "0" * 64}
        refresh_input(row, recipe)
        refresh_vector(row)
        rows.append(row)
    bundle = {"schema": subject.SCHEMA, "profile": declared, "rows": rows,
              "producer_receipt": {"schema": subject.PRODUCER_SCHEMA,
                                   "artifact_binding": {"path": "synthetic-unread-producer.json", "bytes": 1234,
                                                        "sha256": "d" * 64}, "rows": []}}
    sync(bundle)
    return bundle, expected(bundle)


def validate(bundle, pins):
    return subject.validate_lane_bundle(bundle, expected_bindings=pins)


def assert_diagnostic(value):
    assert value["status"] == "validated_declared_representation_identity_only"
    assert value["verification_status"] == value["admission_status"] == "pending"
    assert value["masks"] == dict.fromkeys(subject.MASKS, 0)
    assert all(type(item) is int and item == 0 for item in value["masks"].values())
    assert all(value[field] is False for field in subject.FALSE)
    for field in ("normalization_performed", "padding_or_truncation_performed", "token_receipt_contents_verified",
                  "leanstral_runtime_qualified"):
        assert value[field] is False
    for field in ("model_calls", "encoder_calls", "prover_calls", "optimizer_updates"):
        assert type(value[field]) is int and value[field] == 0
    assert all(row["context_resolved"] is False for row in value["rows"])
    assert value["content_sha256"] == digest({key: item for key, item in value.items() if key != "content_sha256"})


@pytest.mark.parametrize("lane,stage", [("legacy8", "historical_linguistic_features"),
                                       ("native384", "raw_embedding"), ("native768", "raw_embedding")])
def test_raw_lanes_preserve_declared_values_with_no_runtime_authority(lane, stage):
    bundle, pins = case(lane, stage)
    before = deepcopy(bundle)
    result = validate(bundle, pins)
    assert_diagnostic(result)
    assert result["available_count"] == result["row_count"] == 2
    assert result["profile_sha256"] == digest(bundle["profile"])
    assert result["producer_receipt_sha256"] == digest(bundle["producer_receipt"])
    assert result["bundle_sha256"] == digest(bundle)
    assert bundle == before


@pytest.mark.parametrize("stage,width", [("learned_latent", 8), ("learned_projection", 384),
                                        ("reconstruction", 384), ("decoder_condition", 32)])
def test_checkpoint_bound_learned_views_preserve_nonunit_values(stage, width):
    bundle, _ = case("native384", stage, dimension=width)
    bundle["rows"][0]["vector"][0] = 5.5
    refresh_vector(bundle["rows"][0])
    sync(bundle)
    result = validate(bundle, expected(bundle))
    assert_diagnostic(result)
    assert result["dimension"] == width and result["stage"] == stage
    assert bundle["rows"][0]["vector"][0] == 5.5


def test_leanstral_final_hidden_declaration_never_attests_runtime_or_logit_semantics():
    bundle, pins = case("leanstral", "final_hidden_embedding")
    result = validate(bundle, pins)
    assert_diagnostic(result)
    assert result["dimension"] == 4096
    assert result["producer_identity_authenticated"] is result["runtime_computation_proven"] is False


def test_learned_legacy8_requires_its_own_profile_instead_of_reusing_historical_features():
    raw_features, raw_pins = case("legacy8", "historical_linguistic_features")
    learned, learned_pins = case("legacy8", "learned_latent", precision="float32")
    assert raw_features["profile"]["dimension"] == learned["profile"]["dimension"] == 8
    assert raw_pins["inputs"] == learned_pins["inputs"]
    assert_diagnostic(validate(learned, learned_pins))
    with pytest.raises(ValueError, match="externally pinned producer/stage profile"):
        validate(learned, raw_pins)


@pytest.mark.parametrize("recipe", sorted(subject.RECIPES))
def test_context_twins_keep_distinct_inputs_even_with_identical_vectors(recipe):
    bundle, _ = case(recipe=recipe, context_twins=True)
    bundle["rows"][1]["vector"] = deepcopy(bundle["rows"][0]["vector"])
    refresh_vector(bundle["rows"][1])
    sync(bundle)
    result = validate(bundle, expected(bundle))
    assert_diagnostic(result)
    assert len({row["input_sha256"] for row in result["rows"]}) == 2
    assert len({row["vector_sha256"] for row in result["rows"]}) == 1
    assert len({row["source_sha256"] for row in result["rows"]}) == 1
    assert all(row["context_forwarded"] is (recipe == "role_marked_declared_context/v1") for row in result["rows"])
    expected_text_count = 2 if recipe == "role_marked_declared_context/v1" else 1
    assert len({row["encoder_text_sha256"] for row in result["rows"]}) == expected_text_count


def test_raw_source_and_empty_assumption_frame_are_distinct_recipes_and_encoder_inputs():
    source, source_pins = case()
    frame, frame_pins = case(recipe="role_marked_source_frame/v1")
    assert source_pins["inputs"] == frame_pins["inputs"]
    assert source["rows"][0]["encoder_text"] != frame["rows"][0]["encoder_text"]
    assert source_pins["profile_sha256"] != frame_pins["profile_sha256"]
    with pytest.raises(ValueError, match="externally pinned"):
        validate(frame, source_pins)


@pytest.mark.parametrize("attack", ["swap_vectors", "swap_tokens", "swap_sources", "swap_contexts",
                                    "swap_rows", "rewrite_source", "rewrite_receipt_artifact"])
def test_fully_resealed_substitution_cannot_cross_immutable_external_producer_pins(attack):
    bundle, pins = case(context_twins=True, recipe="role_marked_declared_context/v1")
    first, second = bundle["rows"]
    if attack == "swap_vectors":
        first["vector"], second["vector"] = second["vector"], first["vector"]
        for row in bundle["rows"]:
            refresh_vector(row)
    elif attack == "swap_tokens":
        first["token_receipt_sha256"], second["token_receipt_sha256"] = second["token_receipt_sha256"], first["token_receipt_sha256"]
    elif attack == "swap_sources":
        second["input"]["source_text"] = "A second, foreign source that is also syntactically ordinary."
        first["input"], second["input"] = second["input"], first["input"]
        for row in bundle["rows"]:
            refresh_input(row, bundle["profile"]["inference_input_recipe"])
    elif attack == "swap_contexts":
        first["input"]["context"], second["input"]["context"] = second["input"]["context"], first["input"]["context"]
        for row in bundle["rows"]:
            refresh_input(row, bundle["profile"]["inference_input_recipe"])
    elif attack == "swap_rows":
        bundle["rows"].reverse()
    elif attack == "rewrite_source":
        first["input"]["source_text"] += " with an unreviewed qualification"
        refresh_input(first, bundle["profile"]["inference_input_recipe"])
    else:
        bundle["producer_receipt"]["artifact_binding"]["sha256"] = "e" * 64
    sync(bundle)
    with pytest.raises(ValueError, match="externally pinned producer rows"):
        validate(bundle, pins)


@pytest.mark.parametrize("field", ["vector", "token_receipt_sha256", "upstream_vector_sha256", "reason", "producer_row_sha256"])
def test_row_only_forgery_is_rejected_even_when_outer_bundle_is_resealed(field):
    bundle, pins = case("native384", "learned_projection")
    row = bundle["rows"][0]
    if field == "vector":
        row["vector"] = deepcopy(bundle["rows"][1]["vector"])
        refresh_vector(row)
    elif field == "reason":
        row["status"] = "ablation_zero"
        row["reason"] = "A forged zero diagnostic"
        row["vector"] = [0.0] * 384
        refresh_vector(row)
    else:
        row[field] = "f" * 64
    seal(bundle)
    with pytest.raises(ValueError, match="bound producer row"):
        validate(bundle, pins)


def test_external_source_context_pin_remains_independent_of_newly_selected_producer_receipt():
    bundle, original = case(context_twins=True)
    row = bundle["rows"][0]
    row["input"]["context"]["text"] += " This is a different assumption."
    refresh_input(row, bundle["profile"]["inference_input_recipe"])
    sync(bundle)
    new_receipt_pins = expected(bundle)
    new_receipt_pins["inputs"] = original["inputs"]
    with pytest.raises(ValueError, match="externally pinned source/context input"):
        validate(bundle, new_receipt_pins)


@pytest.mark.parametrize("field", ["profile_sha256", "producer_receipt_sha256"])
def test_external_content_pins_include_the_sealed_object_not_only_its_internal_checksum(field):
    bundle, pins = case()
    nested = "profile" if field == "profile_sha256" else "producer_receipt"
    pins[field] = bundle[nested]["content_sha256"]
    assert pins[field] != digest(bundle[nested])
    with pytest.raises(ValueError, match="externally pinned"):
        validate(bundle, pins)


@pytest.mark.parametrize("field", ["stage", "dimension", "profile_id", "model_id", "model_revision", "code_sha256",
                                   "model_assets_sha256", "checkpoint_sha256", "pooling", "normalization", "precision",
                                   "recipe"])
def test_locally_valid_foreign_profile_cannot_replace_the_externally_selected_profile(field):
    bundle, pins = case("native384", "learned_projection")
    value = bundle["profile"]
    if field == "stage":
        value[field] = "reconstruction"
    elif field == "dimension":
        value[field] = 8
        for row in bundle["rows"]:
            row["vector"] = row["vector"][:8]
            refresh_vector(row)
    elif field in {"profile_id", "model_id", "model_revision"}:
        value["producer"][field] = "a-foreign-same-width-producer"
    elif field in {"code_sha256", "model_assets_sha256", "checkpoint_sha256"}:
        value["producer"][field] = "e" * 64
    elif field == "pooling":
        value[field]["endpoint"] = "a-foreign-layer-or-logits"
    elif field == "normalization":
        value[field] = {"kind": "l2", "unit_tolerance": 1e-5}
    elif field == "precision":
        value[field] = "float64"
    else:
        value["fit_input_recipe"] = value["inference_input_recipe"] = "role_marked_source_frame/v1"
        for row in bundle["rows"]:
            refresh_input(row, value["inference_input_recipe"])
    sync(bundle)
    with pytest.raises(ValueError, match="externally pinned producer/stage profile"):
        validate(bundle, pins)


@pytest.mark.parametrize("mutation", ["raw384_cls", "raw768_mean", "raw384_8", "raw768_384", "raw_float64",
                                     "raw_none_norm", "raw_checkpoint", "historical_learned_pool", "historical_float32",
                                     "historical_checkpoint", "historical_native_lane", "derived_no_checkpoint",
                                     "derived_mean", "derived_leanstral", "final_hidden_native_lane", "final_hidden_cls",
                                     "final_hidden_no_checkpoint", "fit_recipe_mismatch", "unknown_recipe"])
def test_rehashed_and_externally_repinned_stage_impersonation_still_fails_policy(mutation):
    if mutation.startswith("historical"):
        bundle, _ = case("legacy8", "historical_linguistic_features")
    elif mutation.startswith("derived"):
        bundle, _ = case("native384", "learned_latent", dimension=8)
    elif mutation.startswith("final_hidden"):
        bundle, _ = case("leanstral", "final_hidden_embedding")
    else:
        bundle, _ = case("native768" if mutation.startswith("raw768") else "native384")
    value = bundle["profile"]
    if mutation in {"raw384_cls", "raw768_mean", "historical_learned_pool", "derived_mean", "final_hidden_cls"}:
        value["pooling"]["method"] = {"raw384_cls": "cls", "raw768_mean": "mean", "historical_learned_pool": "tensor_endpoint",
                                      "derived_mean": "mean", "final_hidden_cls": "cls"}[mutation]
    elif mutation in {"raw384_8", "raw768_384"}:
        value["dimension"] = 8 if mutation == "raw384_8" else 384
    elif mutation in {"raw_float64", "historical_float32"}:
        value["precision"] = "float64" if mutation == "raw_float64" else "float32"
    elif mutation == "raw_none_norm":
        value["normalization"] = {"kind": "none", "unit_tolerance": None}
    elif mutation in {"raw_checkpoint", "historical_checkpoint"}:
        value["producer"]["checkpoint_sha256"] = "c" * 64
    elif mutation in {"derived_no_checkpoint", "final_hidden_no_checkpoint"}:
        value["producer"]["checkpoint_sha256"] = None
    elif mutation in {"historical_native_lane", "derived_leanstral", "final_hidden_native_lane"}:
        value["lane_id"] = "leanstral" if mutation == "derived_leanstral" else "native384"
    elif mutation == "fit_recipe_mismatch":
        value["fit_input_recipe"] = "role_marked_declared_context/v1"
    else:
        value["fit_input_recipe"] = value["inference_input_recipe"] = "unknown-serialization/v9"
    sync(bundle)
    with pytest.raises(ValueError):
        validate(bundle, expected(bundle))


@pytest.mark.parametrize("mutation", ["missing_upstream", "raw_has_upstream"])
def test_stage_specific_upstream_binding_requirements_are_enforced(mutation):
    bundle, _ = case(stage="learned_projection" if mutation == "missing_upstream" else "raw_embedding")
    bundle["rows"][0]["upstream_vector_sha256"] = None if mutation == "missing_upstream" else "e" * 64
    sync(bundle)
    with pytest.raises(ValueError, match="upstream|derived"):
        validate(bundle, expected(bundle))


def test_unavailable_and_zero_ablation_are_separate_preserved_outcomes():
    bundle, pins = case(statuses=("available", "unavailable", "ablation_zero"))
    result = validate(bundle, pins)
    assert_diagnostic(result)
    assert result["row_count"] == 3
    assert (result["available_count"], result["unavailable_count"], result["zero_ablation_count"]) == (1, 1, 1)
    assert bundle["rows"][1]["vector"] is bundle["rows"][1]["vector_sha256"] is None
    assert all(value == 0.0 for value in bundle["rows"][2]["vector"])


@pytest.mark.parametrize("mutation", ["unavailable_padded", "unavailable_digest", "unavailable_no_reason", "available_zero",
                                     "available_reason", "zero_nonzero", "zero_no_reason"])
def test_unavailable_or_ablation_cannot_be_laundered_into_real_vectors(mutation):
    bundle, _ = case(stage="learned_projection", statuses=("available", "unavailable", "ablation_zero"))
    first, missing, zero = bundle["rows"]
    if mutation == "unavailable_padded":
        missing["vector"] = [0.0] * 384
        refresh_vector(missing)
    elif mutation == "unavailable_digest":
        missing["vector_sha256"] = "e" * 64
    elif mutation == "unavailable_no_reason":
        missing["reason"] = None
    elif mutation == "available_zero":
        first["vector"] = [0.0] * 384
        refresh_vector(first)
    elif mutation == "available_reason":
        first["reason"] = "A real vector was withheld"
    elif mutation == "zero_nonzero":
        zero["vector"][0] = 1.0
        refresh_vector(zero)
    elif mutation == "zero_no_reason":
        zero["reason"] = None
    sync(bundle)
    with pytest.raises(ValueError):
        validate(bundle, expected(bundle))


def test_unavailable_derived_view_can_preserve_missing_upstream_without_inventing_a_vector():
    bundle, _ = case(stage="learned_projection", statuses=("unavailable",))
    row = bundle["rows"][0]
    row["upstream_vector_sha256"] = None
    row["reason"] = "The declared upstream producer has no available source vector."
    sync(bundle)
    result = validate(bundle, expected(bundle))
    assert_diagnostic(result)
    assert result["row_count"] == result["unavailable_count"] == 1
    assert result["available_count"] == result["zero_ablation_count"] == 0
    assert row["vector"] is row["vector_sha256"] is row["upstream_vector_sha256"] is None


@pytest.mark.parametrize("value", [True, 1, 0.1, 1e100])
def test_native_float32_values_cannot_be_reconstructed_from_numeric_aliases(value):
    bundle, _ = case(stage="learned_projection")
    bundle["rows"][0]["vector"][0] = value
    refresh_vector(bundle["rows"][0])
    sync(bundle)
    with pytest.raises(ValueError, match="float"):
        validate(bundle, expected(bundle))


def test_decimal6_features_are_preserved_without_float32_conversion():
    bundle, _ = case("legacy8", "historical_linguistic_features")
    bundle["rows"][0]["vector"] = [0.6, 0.8] + [0.0] * 6
    refresh_vector(bundle["rows"][0])
    sync(bundle)
    result = validate(bundle, expected(bundle))
    assert_diagnostic(result)
    assert bundle["rows"][0]["vector"][:2] == [0.6, 0.8]
    bundle["rows"][0]["vector"][0] = 0.6000001
    refresh_vector(bundle["rows"][0])
    sync(bundle)
    with pytest.raises(ValueError, match="round6"):
        validate(bundle, expected(bundle))


def test_declared_float64_derived_values_are_not_silently_converted_to_float32():
    bundle, _ = case(stage="learned_projection", precision="float64")
    bundle["rows"][0]["vector"][0] = 0.1
    refresh_vector(bundle["rows"][0])
    sync(bundle)
    assert_diagnostic(validate(bundle, expected(bundle)))
    assert bundle["rows"][0]["vector"][0] == 0.1
    bundle["rows"][0]["vector"][:4] = [1e308] * 4
    refresh_vector(bundle["rows"][0])
    sync(bundle)
    with pytest.raises(ValueError, match="nonfinite norm"):
        validate(bundle, expected(bundle))


def test_nonunit_raw_vector_and_declared_norm_laundering_fail():
    bundle, _ = case()
    bundle["rows"][0]["vector"][0] = 2.0
    refresh_vector(bundle["rows"][0])
    sync(bundle)
    with pytest.raises(ValueError, match="L2"):
        validate(bundle, expected(bundle))
    bundle["profile"]["normalization"]["unit_tolerance"] = 1.0
    sync(bundle)
    with pytest.raises(ValueError, match="tolerance"):
        validate(bundle, expected(bundle))


def test_signed_zero_serialization_cannot_be_swapped_under_arithmetic_equality():
    bundle, _ = case()
    bundle["rows"][0]["vector"][1] = -0.0
    refresh_vector(bundle["rows"][0])
    sync(bundle)
    pins = expected(bundle)
    original = bundle["rows"][0]["vector_sha256"]
    validate(bundle, pins)
    bundle["rows"][0]["vector"][1] = 0.0
    refresh_vector(bundle["rows"][0])
    assert bundle["rows"][0]["vector_sha256"] != original
    seal(bundle)
    with pytest.raises(ValueError, match="bound producer row"):
        validate(bundle, pins)


@pytest.mark.parametrize("recipe", ["role_marked_source_frame/v1", "role_marked_declared_context/v1"])
@pytest.mark.parametrize("change", ["whitespace", "ascii_escape", "key_order", "drop_roles", "context_frame_confusion"])
def test_exact_declared_serialized_encoder_text_is_not_reformatted_or_inferred(recipe, change):
    bundle, _ = case(recipe=recipe, context_twins=True)
    row = bundle["rows"][0]
    structured = json.loads(row["encoder_text"])
    if change == "whitespace":
        row["encoder_text"] = json.dumps(structured, sort_keys=True, ensure_ascii=False)
    elif change == "ascii_escape":
        row["encoder_text"] = json.dumps(structured, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    elif change == "key_order":
        row["encoder_text"] = json.dumps({key: structured[key] for key in reversed(list(structured))},
                                         separators=(",", ":"), ensure_ascii=False)
    elif change == "drop_roles":
        row["encoder_text"] = raw({"source": row["input"]["source_text"], "context": row["input"]["context"]["text"]}).decode()
    else:
        other = "role_marked_source_frame/v1" if recipe == "role_marked_declared_context/v1" else "role_marked_declared_context/v1"
        row["encoder_text"] = encoder_text(row["input"], other)
    row["encoder_text_sha256"] = text_sha(row["encoder_text"])
    sync(bundle)
    with pytest.raises(ValueError, match="serialized encoder input recipe"):
        validate(bundle, expected(bundle))


def test_internal_feature_whitespace_normalization_cannot_replace_exact_source_pin():
    bundle, pins = case("legacy8", "historical_linguistic_features")
    row = bundle["rows"][0]
    row["input"]["source_text"] = row["input"]["source_text"].replace(" ", "  ")
    refresh_input(row, "exact_source_only/v1")
    sync(bundle)
    with pytest.raises(ValueError, match="externally pinned producer rows"):
        validate(bundle, pins)


def test_token_digest_is_a_binding_only_and_never_a_tokenization_replay():
    bundle, _ = case("native768")
    bundle["rows"][0]["token_receipt_sha256"] = None
    sync(bundle)
    result = validate(bundle, expected(bundle))
    assert result["token_receipt_contents_verified"] is False
    assert_diagnostic(result)


@pytest.mark.parametrize("mutation", ["context_hash", "input_hash", "encoder_hash", "vector_hash", "producer_hash",
                                     "context_extra", "binding_extra", "context_nonempty_none", "missing_declared_text",
                                     "unknown_role", "opaque_binding_nonstr", "duplicate_id", "reverse_bundle_only",
                                     "reverse_input_only", "missing_producer_row", "missing_input", "missing_row"])
def test_exact_source_context_row_and_producer_join_guards(mutation):
    bundle, _ = case(context_twins=True)
    row = bundle["rows"][0]
    if mutation in {"context_hash", "input_hash", "encoder_hash", "vector_hash", "producer_hash"}:
        if mutation == "context_hash":
            row["input"]["context"]["sha256"] = "e" * 64
        else:
            row[{"input_hash": "input_sha256", "encoder_hash": "encoder_text_sha256", "vector_hash": "vector_sha256",
                 "producer_hash": "producer_row_sha256"}[mutation]] = "e" * 64
    elif mutation == "context_extra":
        row["input"]["context"]["context_resolved"] = True
    elif mutation == "binding_extra":
        row["input"]["context"]["bindings"]["record"]["authenticated"] = True
    elif mutation == "context_nonempty_none":
        row["input"]["context"]["role"] = "none_required"
    elif mutation == "missing_declared_text":
        row["input"]["context"]["text"] = ""
        row["input"]["context"]["sha256"] = text_sha("")
    elif mutation == "unknown_role":
        row["input"]["context"]["role"] = "resolved_by_model"
    elif mutation == "opaque_binding_nonstr":
        row["input"]["context"]["bindings"]["record"]["value"] = {"canonical_ir": {}}
    elif mutation == "duplicate_id":
        bundle["rows"][1]["id"] = row["id"]
    if mutation.startswith("context_") or mutation in {"binding_extra", "missing_declared_text", "unknown_role", "opaque_binding_nonstr"}:
        row["input_sha256"] = digest(row["input"])
    # Structural cases receive matching new external pins; the invalid join or
    # schema must still be rejected rather than masked by stale expected seals.
    sync(bundle, producer_rows=mutation != "producer_hash")
    pins = expected(bundle)
    if mutation == "reverse_bundle_only":
        bundle["rows"].reverse()
        seal(bundle)
    elif mutation == "reverse_input_only":
        pins["inputs"].reverse()
    elif mutation == "missing_producer_row":
        bundle["producer_receipt"]["rows"].pop()
        seal(bundle["producer_receipt"])
        seal(bundle)
        pins = expected(bundle)
    elif mutation == "missing_input":
        pins["inputs"].pop()
    elif mutation == "missing_row":
        bundle["rows"].pop()
        seal(bundle)
    with pytest.raises(ValueError):
        validate(bundle, pins)


@pytest.mark.parametrize("location", ["bundle", "profile", "producer", "pooling", "normalization", "receipt", "artifact",
                                     "receipt_row", "row", "input", "context", "binding", "expected", "expected_input"])
def test_authority_or_target_injection_is_rejected_at_each_closed_boundary(location):
    bundle, pins = case(context_twins=True)
    targets = {"bundle": bundle, "profile": bundle["profile"], "producer": bundle["profile"]["producer"],
               "pooling": bundle["profile"]["pooling"], "normalization": bundle["profile"]["normalization"],
               "receipt": bundle["producer_receipt"], "artifact": bundle["producer_receipt"]["artifact_binding"],
               "receipt_row": bundle["producer_receipt"]["rows"][0], "row": bundle["rows"][0],
               "input": bundle["rows"][0]["input"], "context": bundle["rows"][0]["input"]["context"],
               "binding": bundle["rows"][0]["input"]["context"]["bindings"]["record"],
               "expected": pins, "expected_input": pins["inputs"][0]}
    targets[location]["accepted"] = True
    # Preserve extra fields instead of silently stripping the injected claim.
    seal(bundle["profile"])
    bundle["producer_receipt"]["profile_sha256"] = digest(bundle["profile"])
    seal(bundle["producer_receipt"])
    seal(bundle)
    if location not in {"expected", "expected_input"}:
        pins = expected(bundle)
    with pytest.raises(ValueError):
        validate(bundle, pins)


@pytest.mark.parametrize("location,value", [("dimension", True), ("dimension", 384.0), ("dimension", 0),
                                            ("dimension", 8193), ("artifact_bytes", True), ("artifact_bytes", 0),
                                            ("artifact_bytes", 268435457), ("unit_tolerance", True),
                                            ("unit_tolerance", 0), ("unit_tolerance", -0.1),
                                            ("none_tolerance", 1e-5), ("stage", True), ("lane_id", True),
                                            ("precision", "float16"), ("pooling", "logits"), ("schema", "foreign/v1")])
def test_type_aliases_and_profile_geometry_bounds_do_not_acquire_authority(location, value):
    bundle, _ = case(stage="learned_projection" if location == "none_tolerance" else "raw_embedding")
    if location == "artifact_bytes":
        bundle["producer_receipt"]["artifact_binding"]["bytes"] = value
    elif location in {"unit_tolerance", "none_tolerance"}:
        bundle["profile"]["normalization"]["unit_tolerance"] = value
    elif location == "pooling":
        bundle["profile"]["pooling"]["method"] = value
    else:
        bundle["profile"][location] = value
    sync(bundle)
    with pytest.raises(ValueError):
        validate(bundle, expected(bundle))


@pytest.mark.parametrize("field", ["bundle", "profile", "producer_receipt"])
def test_local_content_seals_are_required_in_addition_to_external_pins(field):
    bundle, _ = case()
    (bundle if field == "bundle" else bundle[field])["content_sha256"] = "e" * 64
    if field != "bundle":
        seal(bundle)
    with pytest.raises(ValueError, match="seal"):
        validate(bundle, expected(bundle))


@pytest.mark.parametrize("field", ["profile_sha256", "producer_receipt_sha256"])
@pytest.mark.parametrize("bad", [None, True, "a" * 63, "A" * 64, "0" * 64])
def test_external_identity_pins_are_required_and_exact(field, bad):
    bundle, pins = case()
    pins[field] = bad
    with pytest.raises(ValueError):
        validate(bundle, pins)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"), "\ud800", object()])
def test_nonfinite_non_utf8_or_ordinary_json_violations_fail_without_optional_work(bad):
    bundle, pins = case()
    bundle["rows"][0]["vector"][0] = bad
    with pytest.raises(ValueError):
        validate(bundle, pins)


def test_cycles_node_depth_bytes_and_row_bounds_fail_as_value_error(monkeypatch):
    for constant, limit in (("MAX_JSON_NODES", 20), ("MAX_JSON_DEPTH", 3), ("MAX_BYTES", 100), ("MAX_ROWS", 1)):
        bundle, pins = case()
        with monkeypatch.context() as patch:
            patch.setattr(subject, constant, limit)
            with pytest.raises(ValueError):
                validate(bundle, pins)
    bundle, pins = case()
    bundle["rows"][0]["input"]["cyclic"] = bundle
    with pytest.raises(ValueError):
        validate(bundle, pins)
    bundle, pins = case()
    bundle["rows"] = []
    sync(bundle)
    with pytest.raises(ValueError, match="complete ordered"):
        validate(bundle, expected(bundle))


def test_result_is_detached_and_repeatable_without_reading_the_declared_artifact(monkeypatch):
    bundle, pins = case()
    before = deepcopy(bundle)
    before_pins = deepcopy(pins)

    def forbidden(*args, **kwargs):
        raise AssertionError("dictionary validator attempted artifact or model I/O")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    result = validate(bundle, pins)
    assert result == validate(bundle, pins)
    assert_diagnostic(result)
    result["rows"][0]["id"] = "mutated-return-value"
    result["masks"]["contrastive_supervision"] = 1
    assert bundle == before and pins == before_pins
    assert validate(bundle, pins)["rows"][0]["id"] != result["rows"][0]["id"]


def test_import_and_validation_do_not_load_optional_numeric_or_proof_stacks():
    code = r"""
import importlib, importlib.abc, sys
class Reject(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'torch', 'numpy', 'spacy', 'transformers', 'sentence_transformers', 'z3', 'lean'}:
            raise AssertionError('optional model/prover import: ' + fullname)
sys.meta_path.insert(0, Reject())
s = importlib.import_module('ipfs_datasets_py.logic.formalization.autoencoder.alignment_lane_bundle')
try:
    s.validate_lane_bundle({}, expected_bindings={})
except ValueError:
    pass
else:
    raise AssertionError('empty bundle was accepted')
assert all(name not in sys.modules for name in ('torch','numpy','spacy','transformers','z3','lean'))
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=20,
                            cwd=Path(subject.__file__).resolve().parents[4])
    assert result.returncode == 0, result.stderr
