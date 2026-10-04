"""Numerical context diagnostics use marked fixtures and never load encoders."""
from __future__ import annotations

import builtins
import hashlib
import json
import math
import struct
from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import alignment_context_assay as subject
from ipfs_datasets_py.logic.formalization.autoencoder import (
    alignment_context_embeddings as context_owner,
)
from ipfs_datasets_py.logic.formalization.autoencoder import (
    alignment_richer_embeddings as source_owner,
)
from ipfs_datasets_py.logic.formalization.autoencoder import alignment_richer_panel as panel_owner


@pytest.fixture(scope="module")
def inputs():
    # This public authored fixture has no sealed input or independently reviewed gold.
    panel = panel_owner.build_alignment_richer_panel()
    return context_owner.prepare_context_embedding_inputs(panel), source_owner.prepare_richer_embedding_inputs(panel)


def _axis(dimension, index=0):
    return [float(column == index) for column in range(dimension)]


def _float32(value):
    return struct.unpack(">f", struct.pack(">f", value))[0]


def _raw_lane(raw_inputs, lane_id="native384", vectors=None, missing_ids=()):
    dimension = source_owner.DIMENSIONS[lane_id]
    receipts = []
    for row in raw_inputs["rows"]:
        if row["id"] in missing_ids:
            receipts.append(source_owner._receipt(row, None, token_count=513, status="token_limit_exceeded"))
        else:
            vector = vectors(row, dimension) if vectors else _axis(dimension)
            receipts.append(source_owner._receipt(row, vector, token_count=2))
    return source_owner._lane(raw_inputs, lane_id, receipts,
        source_owner._backend("injected-context-assay-test-only", execution_kind="injected_fixture"),
        status="diagnostic_fixture", model_inference_executed=False, encoder_execution_executed=False)


def _context_lane(context_inputs, lane_id="native384", vectors=None, missing_ids=()):
    transport = context_owner.prepare_context_transport(context_inputs)
    outer_rows = {row["id"]: row for row in context_inputs["rows"]}
    inner = _raw_lane(transport, lane_id,
        vectors=(lambda row, dimension: vectors(outer_rows[row["id"]], dimension)) if vectors else None,
        missing_ids=missing_ids)
    return context_owner._wrap_context_lane(context_inputs, inner)


def _compare(inputs, lane_id="native384", raw=None, contextual=None):
    framed_inputs, raw_inputs = inputs
    return subject.compare_context_embeddings(framed_inputs, raw_inputs,
        raw if raw is not None else _raw_lane(raw_inputs, lane_id),
        contextual if contextual is not None else _context_lane(framed_inputs, lane_id))


def _record(assay, identity):
    return next(row for row in assay["records"] if row["original_input_sha256"] == identity)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                     allow_nan=False).encode("utf-8")).hexdigest()


def _assert_no_authority(assay):
    for name in subject._AUTHORITY:
        assert assay[name] is False
    assert assay["vector_separation_establishes_fidelity"] is False
    assert assay["independent_replay_established"] is False
    assert assay["general_encoder_determinism_established"] is False
    assert assay["runtime_cryptographically_attested"] is False
    assert assay["diagnostic_fixture"] is True
    assert assay["evidence_scope"] == "diagnostic_fixture"
    assert assay["native_receipt_evidence_available"] is False
    for name in ("model_calls", "provider_calls", "encoder_calls", "prover_calls"):
        assert assay[name] == 0


@pytest.mark.parametrize("lane_id,dimension", [("legacy8", 8), ("native384", 384), ("native768", 768)])
def test_all_native_widths_bind_complete_34_originals_and_68_role_framings_without_execution(inputs, lane_id, dimension):
    before = deepcopy(inputs)
    assay = _compare(inputs, lane_id)
    assert assay["lane_id"] == lane_id and assay["dimension"] == dimension
    assert assay["status"] == "complete"
    assert assay["original_input_count"] == len(assay["records"]) == 34
    assert assay["framed_input_count"] == 68
    assert assay["available_comparison_count"] == assay["comparison_count"] == 102
    assert assay["non_context_controls"] == 32 and assay["explicit_context_inputs"] == 2
    assert len(assay["context_pairs"]) == 1
    assert assay["summaries"]["none_required"]["original_inputs"] == 32
    assert assay["summaries"]["explicit_assumptions"]["original_inputs"] == 2
    assert inputs == before
    _assert_no_authority(assay)


def test_common_shell_is_counted_separately_from_identical_fixture_vectors(inputs):
    assay = _compare(inputs)
    formatting = assay["summaries"]["all_inputs"]["comparisons"]["formatting"]
    context = assay["summaries"]["all_inputs"]["comparisons"]["declared_context"]
    assert formatting["equal_encoder_text_count"] == 0
    assert formatting["exact_vector_hash_equal_count"] == 34
    assert context["equal_encoder_text_count"] == 32
    assert context["exact_vector_values_equal_count"] == 34
    # Two different context packets can collide in a diagnostic representation.
    pair = assay["context_pairs"][0]
    assert pair["arms"]["raw_source"]["encoder_text_equal"] is True
    assert pair["arms"]["source_frame_only"]["encoder_text_equal"] is True
    assert pair["arms"]["declared_context"]["encoder_text_equal"] is False
    assert pair["arms"]["declared_context"]["unit_cosine_distance"] == 0
    assert pair["distinct_declared_contexts"] is True
    _assert_no_authority(assay)


def test_context_pair_separation_is_observed_without_any_correct_interpretation_claim(inputs):
    framed_inputs, _ = inputs
    identities = sorted({row["original_input_sha256"] for row in framed_inputs["rows"]
                         if row["context"]["role"] == "explicit_assumptions"})
    def vector(row, dimension):
        return _axis(dimension, 1 if row["arm_id"] == "declared_context" and row["original_input_sha256"] == identities[0] else 0)
    assay = _compare(inputs, contextual=_context_lane(framed_inputs, vectors=vector))
    pair = assay["context_pairs"][0]
    assert pair["arms"]["declared_context"]["unit_cosine_similarity"] == 0
    assert pair["arms"]["declared_context"]["unit_cosine_distance"] == 1
    assert pair["arms"]["declared_context"]["normalized_value_l2_distance"] == pytest.approx(math.sqrt(2))
    assert pair["arms"]["raw_source"]["exact_vector_hash_equal"] is True
    assert pair["arms"]["source_frame_only"]["exact_vector_values_equal"] is True
    assert assay["summaries"]["none_required"]["comparisons"]["declared_context"]["within_tolerance_count"] == 32
    assert assay["summaries"]["explicit_assumptions"]["comparisons"]["declared_context"]["means"]["unit_cosine_distance"] == .5
    _assert_no_authority(assay)


def test_framing_effect_and_context_effect_are_distinct_numerical_comparisons(inputs):
    framed_inputs, _ = inputs
    def vector(row, dimension):
        return _axis(dimension, 2 if row["context_forwarded"] else 1)
    assay = _compare(inputs, contextual=_context_lane(framed_inputs, vectors=vector))
    assert assay["summaries"]["all_inputs"]["comparisons"]["formatting"]["means"]["unit_cosine_distance"] == 1
    assert assay["summaries"]["none_required"]["comparisons"]["declared_context"]["means"]["unit_cosine_distance"] == 0
    assert assay["summaries"]["explicit_assumptions"]["comparisons"]["declared_context"]["means"]["unit_cosine_distance"] == 1
    assert assay["summaries"]["all_inputs"]["comparisons"]["total"]["means"]["unit_cosine_distance"] == 1


@pytest.mark.parametrize("difference,within", [(1e-6, True), (1e-4, False)])
def test_equal_text_controls_can_have_small_batch_drift_without_false_rejection(inputs, difference, within):
    framed_inputs, _ = inputs
    def vector(row, dimension):
        output = _axis(dimension)
        if row["arm_id"] == "declared_context":
            output[1] = _float32(difference)
        return output
    assay = _compare(inputs, contextual=_context_lane(framed_inputs, vectors=vector))
    controls = assay["summaries"]["none_required"]["comparisons"]["declared_context"]
    assert controls["equal_encoder_text_count"] == 32
    assert controls["exact_vector_values_equal_count"] == 0
    assert controls["within_tolerance_count"] == (32 if within else 0)
    assert controls["means"]["normalized_value_l2_distance"] == pytest.approx(_float32(difference))
    assert assay["status"] == "complete"
    assert assay["tolerance"] == 1e-5


def test_original_l2_values_preserve_scalar_drift_that_direction_cosine_cannot_show(inputs):
    framed_inputs, _ = inputs
    def vector(row, dimension):
        output = _axis(dimension)
        if row["arm_id"] == "declared_context":
            output[0] = _float32(1 + 2e-6)
        return output
    assay = _compare(inputs, contextual=_context_lane(framed_inputs, vectors=vector))
    controls = assay["summaries"]["none_required"]["comparisons"]["declared_context"]
    assert controls["means"]["unit_cosine_distance"] == 0
    assert controls["means"]["normalized_value_l2_distance"] > 0
    assert controls["exact_vector_values_equal_count"] == 0


def test_signed_zero_numeric_equality_and_original_hash_equality_remain_distinct(inputs):
    framed_inputs, _ = inputs
    def vector(row, dimension):
        output = _axis(dimension)
        if row["arm_id"] == "declared_context":
            output[-1] = -0.0
        return output
    assay = _compare(inputs, contextual=_context_lane(framed_inputs, vectors=vector))
    controls = assay["summaries"]["none_required"]["comparisons"]["declared_context"]
    assert controls["exact_vector_values_equal_count"] == 32
    assert controls["exact_vector_hash_equal_count"] == 0
    assert controls["means"]["normalized_value_l2_distance"] == 0


def test_opposite_directions_have_bounded_cosine_and_correct_l2(inputs):
    framed_inputs, _ = inputs
    def vector(row, dimension):
        output = _axis(dimension)
        if row["arm_id"] == "declared_context":
            output[0] = -1.0
        return output
    assay = _compare(inputs, contextual=_context_lane(framed_inputs, vectors=vector))
    comparisons = assay["summaries"]["all_inputs"]["comparisons"]["declared_context"]
    assert comparisons["means"]["unit_cosine_similarity"] == -1
    assert comparisons["means"]["unit_cosine_distance"] == 2
    assert comparisons["means"]["normalized_value_l2_distance"] == 2


def test_partial_token_limit_receipts_keep_null_unknown_metrics_and_eligible_denominators(inputs):
    framed_inputs, _ = inputs
    row = next(row for row in framed_inputs["rows"] if row["arm_id"] == "declared_context")
    lane = _context_lane(framed_inputs, missing_ids={row["id"]})
    assay = _compare(inputs, contextual=lane)
    record = _record(assay, row["original_input_sha256"])
    assert assay["status"] == "partial" and assay["available_comparison_count"] == 100
    assert record["comparisons"]["formatting"]["status"] == "available"
    for name in ("declared_context", "total"):
        comparison = record["comparisons"][name]
        assert comparison["status"] == "unavailable"
        assert "token_limit_exceeded" in comparison["reason"]
        assert comparison["unit_cosine_distance"] is comparison["normalized_value_l2_distance"] is None
        summary = assay["summaries"]["all_inputs"]["comparisons"][name]
        assert (summary["eligible_count"], summary["unavailable_count"]) == (33, 1)


def test_unavailable_raw_baseline_cannot_yield_a_complete_three_arm_assay(inputs):
    _, raw_inputs = inputs
    lane = source_owner._unavailable(raw_inputs, "native384", "fixture-not-loaded", "not available in isolated test")
    assay = _compare(inputs, raw=lane)
    assert assay["status"] == "partial" and assay["available_comparison_count"] == 34
    for comparison in ("formatting", "total"):
        summary = assay["summaries"]["all_inputs"]["comparisons"][comparison]
        assert (summary["eligible_count"], summary["unavailable_count"]) == (0, 34)
        assert all(value is None for value in summary["means"].values())
    assert assay["context_pairs"][0]["arms"]["raw_source"]["status"] == "unavailable"


def test_unavailable_context_lane_preserves_source_pair_but_no_invented_context_distances(inputs):
    framed_inputs, _ = inputs
    transport = context_owner.prepare_context_transport(framed_inputs)
    inner = source_owner._unavailable(transport, "native384", "fixture-not-loaded", "not available in isolated test")
    lane = context_owner._wrap_context_lane(framed_inputs, inner)
    assay = _compare(inputs, contextual=lane)
    assert assay["status"] == "unavailable" and assay["available_comparison_count"] == 0
    pair = assay["context_pairs"][0]
    assert pair["arms"]["raw_source"]["status"] == "available"
    assert pair["arms"]["declared_context"]["unit_cosine_distance"] is None


def test_native_lane_mismatch_is_rejected_without_padding_or_truncation(inputs):
    framed_inputs, raw_inputs = inputs
    with pytest.raises(ValueError, match="identities or widths"):
        subject.compare_context_embeddings(framed_inputs, raw_inputs,
            _raw_lane(raw_inputs, "legacy8"), _context_lane(framed_inputs, "native384"))


@pytest.mark.parametrize("field", ["target", "split", "reference", "compiler_result", "proof"])
def test_closed_framed_inputs_reject_target_and_outcome_channels_even_if_resealed(inputs, field):
    framed_inputs, raw_inputs = deepcopy(inputs)
    raw = _raw_lane(raw_inputs)
    lane = _context_lane(framed_inputs)
    framed_inputs["rows"][0][field] = "forbidden"
    context_owner._seal(framed_inputs)
    with pytest.raises(ValueError):
        subject.compare_context_embeddings(framed_inputs, raw_inputs, raw, lane)


@pytest.mark.parametrize("mutation", ["hash", "source", "original", "arm", "vector", "numeric_bool", "zero", "width", "authority"])
def test_owner_validation_prevents_corrupted_or_rebound_context_receipts(inputs, mutation):
    framed_inputs, raw_inputs = inputs
    lane = _context_lane(framed_inputs)
    if mutation == "authority":
        lane["qualified"] = True
    else:
        receipt = lane["receipts"][0]
        if mutation == "hash":
            receipt["embedding_sha256"] = "0" * 64
        elif mutation == "source":
            receipt["source_sha256"] = "0" * 64
        elif mutation == "original":
            receipt["original_input_sha256"] = "0" * 64
        elif mutation == "arm":
            receipt["arm_id"] = "invented_arm"
        elif mutation == "numeric_bool":
            receipt["embedding"][0] = True
        elif mutation == "zero":
            receipt["embedding"] = [0.0] * 384
        elif mutation == "width":
            receipt["embedding"] = [1.0] + [0.0] * 767
        else:
            receipt["embedding"][0] = float("nan")
    if mutation != "vector":
        context_owner._seal(lane)
    with pytest.raises(ValueError):
        subject.compare_context_embeddings(framed_inputs, raw_inputs, _raw_lane(raw_inputs), lane)


def test_assay_binding_matches_exact_generations_and_rejects_resealed_result_claims(inputs):
    framed_inputs, raw_inputs = inputs
    raw, lane = _raw_lane(raw_inputs), _context_lane(framed_inputs)
    assay = subject.compare_context_embeddings(framed_inputs, raw_inputs, raw, lane)
    assert assay["bindings"] == {"context_inputs_sha256": _digest(framed_inputs), "raw_source_inputs_sha256": _digest(raw_inputs),
                                 "raw_source_lane_sha256": _digest(raw), "context_lane_sha256": _digest(lane)}
    validated = subject.validate_context_assay(assay, framed_inputs, raw_inputs, raw, lane)
    assert validated["status"] == "validated_integrity_only"
    assert validated["qualified"] is False
    assert validated["semantic_quality_checked"] is False
    assert json.loads(json.dumps(assay, allow_nan=False)) == assay


@pytest.mark.parametrize("mutation", ["extra", "fidelity", "bool_alias", "count", "distance", "tolerance", "fixture", "pair"])
def test_recompute_validator_rejects_unknown_fields_and_json_type_aliases(inputs, mutation):
    framed_inputs, raw_inputs = inputs
    raw, lane = _raw_lane(raw_inputs), _context_lane(framed_inputs)
    assay = subject.compare_context_embeddings(framed_inputs, raw_inputs, raw, lane)
    if mutation == "extra":
        assay["authored_reference"] = "forbidden"
    elif mutation == "fidelity":
        assay["source_fidelity_established"] = True
    elif mutation == "bool_alias":
        assay["qualified"] = 0
    elif mutation == "count":
        assay["original_input_count"] = 34.0
    elif mutation == "distance":
        assay["records"][0]["comparisons"]["formatting"]["unit_cosine_distance"] = .1
    elif mutation == "tolerance":
        assay["tolerance"] = .1
    elif mutation == "fixture":
        assay["diagnostic_fixture"] = False
    else:
        assay["context_pairs"] = []
    assay["assay_sha256"] = _digest({key: value for key, value in assay.items() if key != "assay_sha256"})
    with pytest.raises(ValueError):
        subject.validate_context_assay(assay, framed_inputs, raw_inputs, raw, lane)


def test_reference_free_assay_never_reopens_panel_labels_or_imports_optional_runtimes(inputs, monkeypatch):
    framed_inputs, raw_inputs = inputs
    raw, lane = _raw_lane(raw_inputs), _context_lane(framed_inputs)
    def forbidden_panel(_panel):
        raise AssertionError("assay reopened full panel/targets")
    monkeypatch.setattr(panel_owner, "validate_alignment_richer_panel", forbidden_panel)
    original = builtins.__import__
    forbidden = {"torch", "numpy", "spacy", "transformers", "sentence_transformers", "requests", "httpx", "z3", "cvc5", "openai"}
    def guarded(name, *args, **kwargs):
        assert name.split(".")[0] not in forbidden, name
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded)
    assay = subject.compare_context_embeddings(framed_inputs, raw_inputs, raw, lane)
    subject.validate_context_assay(assay, framed_inputs, raw_inputs, raw, lane)
    _assert_no_authority(assay)
