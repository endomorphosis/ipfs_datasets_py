"""Checkpoint metadata and marked endpoint fixtures; no model/corpus loading."""
from __future__ import annotations

import builtins
import hashlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import (
    alignment_checkpoint_representations as subject,
)
from ipfs_datasets_py.logic.formalization.autoencoder import (
    alignment_representation_retrieval as retrieval,
)
from ipfs_datasets_py.logic.formalization.autoencoder import (
    alignment_richer_embeddings as embeddings,
)
from ipfs_datasets_py.logic.formalization.autoencoder import alignment_richer_panel as panel_owner


@pytest.fixture
def fixture(tmp_path):
    # Reuse the established serialized-teacher fixture, preserving its source
    # files that deliberately raise if anyone attempts to execute them.
    path = Path(__file__).with_name("test_gte_bridge_teacher.py")
    spec = importlib.util.spec_from_file_location("alignment_teacher_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    data = module.fixture.__wrapped__(tmp_path)
    checkpoint = data["checkpoint"]
    checkpoint["config"].update(projection_width=8, hidden_size=32)
    shapes = module.subject._INVENTORY._sequence_shapes(checkpoint, 384)
    checkpoint["model_state"] = {name: [[.125] * shape[1] for _ in range(shape[0])] if len(shape) == 2
                                 else [.125] * shape[0] for name, shape in shapes.items()}
    checkpoint["weights_sha256"] = module.digest(checkpoint["model_state"])
    data["path"].write_bytes(module.raw(checkpoint))
    panel = panel_owner.build_alignment_richer_panel()
    inputs = embeddings.prepare_richer_embedding_inputs(panel)
    native = []
    endpoint_values = {}
    for i, row in enumerate(inputs["rows"]):
        vector = [0.] * 384
        vector[i] = 1.
        native.append(embeddings._receipt(row, vector, token_count=2))
        values = {}
        for key, dimension in subject.ENDPOINTS.items():
            values[key] = [0.] * dimension
            values[key][i % dimension] = .5
        endpoint_values[row["id"]] = values
    lane = embeddings._lane(inputs, "native384", native,
        embeddings._backend("test-only-nonsemantic-fixture", execution_kind="injected_fixture"),
        status="diagnostic_fixture", model_inference_executed=False, encoder_execution_executed=False)
    plan = subject.prepare_source384_representation_plan(inputs, lane, checkpoint_path=data["path"],
        expected_checkpoint_sha256=hashlib.sha256(data["path"].read_bytes()).hexdigest(), preserved_repository_root=data["root"])
    result = subject.diagnostic_source384_representations(plan, inputs, lane, endpoint_values)
    return data, panel, inputs, lane, plan, result


def reseal(value):
    value.pop("payload_sha256", None)
    return subject._seal(value)


def test_exact_input_width_and_distinct_endpoint_widths(fixture):
    _, _, inputs, lane, plan, result = fixture
    assert plan["native_input_dimension"] == 384
    assert plan["endpoint_dimensions"] == {"residual_branch_8": 8, "residual_projection_384": 384, "formula_condition_32": 32}
    assert plan["branch_is_complete_compressed_input"] is False
    assert len(plan["teacher_binding"]["sources"]) == 14
    assert result["status"] == "diagnostic_fixture" and result["row_count"] == 34
    assert result["model_inference_executed"] is False
    assert all(row["context_forwarded"] is False for row in result["rows"])
    assert subject.validate_source384_representations(result, inputs, lane, plan=plan)["independent_output_replay"] is False


@pytest.mark.parametrize("field", sorted(subject.FALSE))
def test_resealed_authority_or_target_access_fails(fixture, field):
    _, _, inputs, _, _, result = fixture
    result[field] = True
    reseal(result)
    with pytest.raises(ValueError, match="authority or target access"):
        subject.validate_source384_representations(result, inputs)


@pytest.mark.parametrize("mutation", ["source", "input_vector", "width", "hash", "norm", "tanh", "extra", "row_count", "relabel"])
def test_resealed_output_linkage_or_geometry_fails(fixture, mutation):
    _, _, inputs, _, _, result = fixture
    row = result["rows"][0]
    if mutation == "source":
        row["source_sha256"] = "a" * 64
    elif mutation == "input_vector":
        row["input_embedding_sha256"] = "a" * 64
    elif mutation == "width":
        row["endpoints"]["formula_condition_32"]["values"].pop()
    elif mutation == "hash":
        row["endpoints"]["residual_branch_8"]["values_sha256"] = "a" * 64
    elif mutation == "norm":
        row["endpoints"]["residual_branch_8"]["norm"] = 7.
    elif mutation == "tanh":
        values = [2.] + [0.] * 7
        row["endpoints"]["residual_branch_8"] = subject._endpoint(values, 8)
    elif mutation == "extra":
        result["unexpected"] = 1
    elif mutation == "row_count":
        result["row_count"] = True
    else:
        result.update(status="produced", model_inference_executed=True, endpoint_inference_executed=True, diagnostic_fixture=False)
    reseal(result)
    with pytest.raises(ValueError):
        subject.validate_source384_representations(result, inputs)


def test_checkpoint_and_preserved_source_drift_fail(fixture):
    data, _, inputs, lane, plan, _ = fixture
    original = data["path"].read_bytes()
    data["path"].write_bytes(original + b" ")
    with pytest.raises(ValueError):
        subject.validate_source384_representation_plan(plan, inputs, lane)
    data["path"].write_bytes(original)
    source = data["root"] / next(iter(data["pins"]))
    source.write_bytes(b"changed")
    with pytest.raises(ValueError):
        subject.validate_source384_representation_plan(plan, inputs, lane)


def test_diagnostic_extraction_refuses_before_optional_stack_import(fixture, monkeypatch):
    _, _, inputs, lane, plan, _ = fixture
    original = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name.split(".")[0] in {"torch", "transformers", "spacy"}:
            raise AssertionError("optional model stack unexpectedly imported")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded)
    with pytest.raises(ValueError, match="observed native"):
        subject.extract_source384_representations(plan, inputs, lane)


def test_preserved_runtime_helpers_exist_without_model_import():
    from ipfs_datasets_py.logic.formalization.autoencoder.gte_decoder_transfer_replay import (
        _exact_float32,
        _numerical_context,
        _original_primary_model,
    )

    assert all(callable(helper) for helper in (_exact_float32, _numerical_context, _original_primary_model))


def test_unavailable_source_lane_preserves_no_outputs(fixture):
    data, _, inputs, _, _, _ = fixture
    lane = embeddings._unavailable(inputs, "native384", "fixture-unavailable", "not executed")
    plan = subject.prepare_source384_representation_plan(inputs, lane, checkpoint_path=data["path"],
        expected_checkpoint_sha256=hashlib.sha256(data["path"].read_bytes()).hexdigest(), preserved_repository_root=data["root"])
    result = subject.extract_source384_representations(plan, inputs, lane)
    assert result["status"] == "unavailable" and result["rows"] == []
    assert subject.validate_source384_representations(result, inputs)["row_count"] == 0


def test_generic_cosine_and_fixed_training_pool_without_padding(fixture):
    _, panel, inputs, _, _, result = fixture
    rankings = retrieval.rank_checkpoint_representations(panel, inputs, result)
    assert len(rankings["candidate_ids"]) == 16 and rankings["query_count"] == 18
    for arm, values in rankings["arms"].items():
        assert values["dimension"] == ({"raw_source_384": 384, **subject.ENDPOINTS})[arm]
        assert values["native_input_dimension"] == 384
        for row in values["rows"]:
            assert len(row["ranked"]) == 5 and len(row["full_pool_ranking"]) == 16
            assert row["full_pool_ranking"] == sorted(row["full_pool_ranking"], key=lambda r: (-r["cosine_similarity"], r["candidate_id"]))
    scores = retrieval.score_checkpoint_representations(panel, rankings, inputs, result)
    for values in scores["arms"].values():
        assert len(values["positive_rows"]) == 8
        assert len(values["negative_diagnostic_rows"]) == 8
        assert len(values["context_diagnostic_rows"]) == 2
        assert all(row["score"]["reference_target_present_in_pool"] is False for row in values["positive_rows"])


def test_valid_development_target_mutation_changes_only_posthoc_scores(fixture):
    _, panel, inputs, _, _, result = fixture
    rankings = retrieval.rank_checkpoint_representations(panel, inputs, result)
    scores = retrieval.score_checkpoint_representations(panel, rankings, inputs, result)
    changed = deepcopy(panel)
    row = next(row for row in changed["rows"] if row["split"] == "validation" and row["row_kind"] == "positive")
    row["target"]["rules"][0]["actor"] = "clerk" if row["target"]["rules"][0]["actor"] != "clerk" else "custodian"
    row["target_sha256"] = panel_owner._digest(row["target"])
    changed["integrity"] = panel_owner._integrity(changed)
    panel_owner.validate_alignment_richer_panel(changed)
    assert retrieval.rank_checkpoint_representations(changed, inputs, result) == rankings
    assert retrieval.score_checkpoint_representations(changed, rankings, inputs, result) != scores


def test_zero_endpoint_directions_do_not_fabricate_rankings(fixture):
    _, panel, inputs, _, _, result = fixture
    for row in result["rows"]:
        row["endpoints"]["formula_condition_32"] = subject._endpoint([0.] * 32, 32)
    reseal(result)
    rankings = retrieval.rank_checkpoint_representations(panel, inputs, result)
    assert all(row["status"] == "unavailable" and row["ranked"] == [] for row in rankings["arms"]["formula_condition_32"]["rows"])
    scores = retrieval.score_checkpoint_representations(panel, rankings, inputs, result)
    assert scores["arms"]["formula_condition_32"]["summary"]["mean_graded_facet_ndcg"] is None


def test_ranking_replay_rejects_resealed_selected_candidates(fixture):
    _, panel, inputs, _, _, result = fixture
    rankings = retrieval.rank_checkpoint_representations(panel, inputs, result)
    rankings["arms"]["formula_condition_32"]["rows"][0]["ranked"].reverse()
    reseal(rankings)
    with pytest.raises(ValueError, match="source-only"):
        retrieval.validate_checkpoint_rankings(rankings, panel, inputs, result)


def test_reconstruction_assay_distinct_from_fidelity_or_raw_identity(fixture):
    _, _, inputs, _, _, result = fixture
    before = json.dumps(result, sort_keys=True)
    assay = retrieval.assay_residual_projection(inputs, result)
    assert assay["summary"]["available_count"] == 34
    assert assay["summary"]["mean_coordinate_mse"] > 0
    assert all(row["raw_identity_baseline_mse"] == 0 for row in assay["records"])
    assert assay["reconstruction_is_fidelity_evidence"] is False
    assert json.dumps(result, sort_keys=True) == before
