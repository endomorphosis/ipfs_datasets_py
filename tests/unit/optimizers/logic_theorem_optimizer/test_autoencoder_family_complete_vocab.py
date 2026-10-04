"""Exact atom retention, bounded allocation and full-support scoring contracts."""
from collections import Counter
from copy import deepcopy
import math

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training as original
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_complete_vocab as complete


def fixtures(payloads, families=None):
    families = families or {"p": "first_order"}
    reports, rows = [], []
    for index, payload in enumerate(payloads):
        projections, row = [], {}
        for name, family in families.items():
            descriptor = {"logic_family": family, "profile": "test", "representation_kind": "native_ast", "producer_id": "test"}
            target = {"projection_id": name, "ready_for_training": True, "payload": payload, **descriptor}
            projections.append(target)
            row[name] = descriptor, Counter(original._atoms(payload))
        reports.append({"domain_id": "intent_ir", "source_digest": f"source-{index}",
            "source_sha256": f"bytes-{index}", "projections": projections})
        rows.append(row)
    return reports, rows


def build(reports, rows, **kwargs):
    return complete.build_complete_space("intent_ir", reports, rows, validation_rows=1,
        latent_width=4, minibatch_size=2, **kwargs)


def metric_spaces():
    descriptor = {"logic_family": "first_order", "profile": None}
    reference = {"domain_id": "intent_ir", "projections": {"p": descriptor},
        "columns": [["p", "a"], ["p", "b"]],
        "feature_selection": {"method": "complete_training_only_original_atoms"}}
    old = {**deepcopy(reference), "columns": [["p", "a"]],
        "feature_selection": {"method": "old_truncated"}}
    return old, reference, descriptor


def test_every_original_atom_and_projection_retained_above_legacy_cap():
    reports, rows = fixtures([{"items": [{"literal": f"term_{index}"} for index in range(1500)]}])
    space = build(reports, rows)
    expected = [[name, atom] for name in sorted(rows[0]) for atom in sorted(rows[0][name][1])]
    assert space["columns"] == expected
    assert len(expected) > original.MAX_FEATURES
    assert space["feature_selection"]["available_atoms"] == space["feature_selection"]["retained_atoms"]
    assert space["feature_selection"]["discarded_atoms"] == 0
    assert space["feature_selection"]["validation_or_test_atoms_used_for_fitting"] is False


def test_positions_source_hashes_and_unknown_fields_are_never_filtered():
    payload = {"source_ref": {"content_sha256": "a" * 64}, "arguments": ["alice", "bob"],
        "unrecognized_semantic_field": {"modal": "obligation"}}
    reports, rows = fixtures([payload])
    space = build(reports, rows)
    for atom in original._atoms(payload):
        assert ["p", atom] in space["columns"]
    changed = {**payload, "arguments": ["bob", "alice"]}
    assert Counter(original._atoms(changed)) != Counter(original._atoms(payload))


def test_training_only_vocabulary_and_size_only_validation_input():
    reports, rows = fixtures([{"actor": "alice"}])
    first = build(reports, rows)
    second = complete.build_complete_space("intent_ir", reports, rows, validation_rows=30,
        latent_width=4, minibatch_size=2)
    assert first["columns"] == second["columns"]
    assert first["training_reports_sha256"] == second["training_reports_sha256"]
    assert first["feature_selection"]["memory_estimate"] != second["feature_selection"]["memory_estimate"]
    with pytest.raises(ValueError, match="validation_rows"):
        complete.build_complete_space("intent_ir", reports, rows, validation_rows=[{"actor": "test-only"}],
            latent_width=4, minibatch_size=2)


@pytest.mark.parametrize("setting,value,reason", [("max_features", 1, "max_features"),
    ("max_atom_bytes", 1, "max_atom_bytes"), ("max_estimated_bytes", 1, "max_estimated_bytes")])
def test_capacity_overrun_rejects_without_truncation(setting, value, reason):
    reports, rows = fixtures([{"actor": "alice"}])
    before = deepcopy(rows)
    with pytest.raises(complete.FeatureCapacityError) as failure:
        build(reports, rows, **{setting: value})
    assert failure.value.to_dict()["reason"] == reason
    assert failure.value.to_dict()["truncated"] is False
    assert failure.value.to_dict()["training_permitted"] is False
    assert rows == before


@pytest.mark.parametrize("corruption", ["omit_atom", "change_count", "omit_projection", "blocked", "descriptor"])
def test_original_report_correspondence_is_checked(corruption):
    reports, rows = fixtures([{"actor": "alice"}], {"p": "first_order", "q": "deontic"})
    if corruption == "omit_atom":
        del rows[0]["p"][1][next(iter(rows[0]["p"][1]))]
    elif corruption == "change_count":
        rows[0]["p"][1][next(iter(rows[0]["p"][1]))] += 1
    elif corruption == "omit_projection":
        del rows[0]["q"]
    elif corruption == "blocked":
        reports[0]["projections"][0]["ready_for_training"] = False
    else:
        rows[0]["p"][0]["logic_family"] = "wrong"
    with pytest.raises(ValueError):
        build(reports, rows)


def test_dense_and_sparse_memory_report_does_not_claim_process_rss():
    estimate = complete.estimate_feature_memory(features=5000, training_rows=6,
        validation_rows=2, projections=4, latent_width=4, minibatch_size=2, training_nonzero_atoms=100)
    assert estimate["dense_estimated_bytes"] == sum(estimate["dense_components"].values())
    assert estimate["sparse_matrix_estimated_bytes"] == sum(estimate["sparse_components"].values())
    assert estimate["hard_rss_bound"] is False
    assert estimate["backend_changed"] is False
    with pytest.raises(complete.FeatureCapacityError, match="inference"):
        complete.guard_inference_memory(features=5000, rows=6, projections=4, latent_width=4,
            max_estimated_bytes=1)


def test_common_support_charges_missing_atoms_without_oracle_prediction_scaling():
    old, reference, descriptor = metric_spaces()
    rows = [{"p": (descriptor, Counter({"a": 1, "b": 1}))}]
    result = complete.common_support_metrics(old, [[1.]], rows, reference_space=reference)
    expected_mse = ((1 - 1 / math.sqrt(2)) ** 2 + .5) / 2
    expected_cosine = 1 - 1 / math.sqrt(2)
    assert result["objective"] == pytest.approx(expected_mse + .1 * expected_cosine)
    assert result["projections"]["p"]["mse"] == pytest.approx(expected_mse)
    assert result["coverage"]["projections"][0]["unknown_target_squared_mass"] == pytest.approx(.5)
    perfect = complete.common_support_metrics(reference, [[1 / math.sqrt(2)] * 2], rows, reference_space=reference)
    assert perfect["objective"] == pytest.approx(0, abs=1e-15)
    assert perfect["evaluation_support_sha256"] == result["evaluation_support_sha256"]


def test_unseen_target_atoms_only_extend_scoring_support_and_keep_denominator_shared():
    old, reference, descriptor = metric_spaces()
    snapshot = deepcopy(reference)
    rows = [{"p": (descriptor, Counter({"a": 1, "novel": 1}))}]
    a = complete.common_support_metrics(old, [[1]], rows, reference_space=reference)
    b = complete.common_support_metrics(reference, [[1, 0]], rows, reference_space=reference)
    assert a["objective"] == b["objective"]
    assert a["evaluation_support_sha256"] == b["evaluation_support_sha256"]
    assert a["projections"]["p"]["support_coordinates"] == 3
    assert a["coverage"]["projections"][0]["unseen_training_distinct_atoms"] == 1
    assert reference == snapshot
    assert a["evaluation_atoms_added_to_fitted_vocabulary"] is False


def test_false_positive_training_coordinates_are_scored():
    _, reference, descriptor = metric_spaces()
    rows = [{"p": (descriptor, Counter({"a": 1}))}]
    clean = complete.common_support_metrics(reference, [[1, 0]], rows, reference_space=reference)
    wrong = complete.common_support_metrics(reference, [[1, 1]], rows, reference_space=reference)
    assert clean["objective"] == pytest.approx(0)
    assert wrong["objective"] > .25


def test_empty_prediction_scores_oov_instead_of_skipping_projection():
    old, reference, descriptor = metric_spaces()
    result = complete.common_support_metrics(old, [[0]], [{"p": (descriptor, Counter({"novel": 1}))}],
        reference_space=reference)
    assert result["objective"] == pytest.approx(1 / 3 + .1)
    assert result["coverage"]["all_target_atoms_scored"]
    assert result["coverage"]["projections"][0]["missing_distinct_atoms"] == 1


def test_macro_family_objective_preserves_multiple_projection_views():
    old, reference, descriptor = metric_spaces()
    reference["projections"].update(q=descriptor.copy(), r={**descriptor, "logic_family": "deontic"})
    reference["columns"].extend([["q", "a"], ["r", "a"]])
    rows = [{name: (desc, Counter({"a": 1})) for name, desc in reference["projections"].items()}]
    result = complete.common_support_metrics(reference, [[1, 0, 0, 1]], rows, reference_space=reference)
    assert result["families"]["first_order"] == pytest.approx((0 + 1.1) / 2)
    assert result["families"]["deontic"] == pytest.approx(0)
    assert result["objective"] == pytest.approx(.275)
    assert set(result["projections"]) == {"p", "q", "r"}


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), 1e200, True, "1"])
def test_prediction_scalars_are_finite_numbers_not_coerced(invalid):
    old, reference, descriptor = metric_spaces()
    with pytest.raises(ValueError):
        complete.common_support_metrics(old, [[invalid]], [{"p": (descriptor, Counter(a=1))}], reference_space=reference)


def test_cpu_tensor_prediction_is_accepted_without_mutation():
    import torch
    old, reference, descriptor = metric_spaces()
    predicted = torch.tensor([[1.]], dtype=torch.float64, requires_grad=True)
    result = complete.common_support_metrics(old, predicted, [{"p": (descriptor, Counter(a=1))}], reference_space=reference)
    assert result["objective"] == pytest.approx(0)
    assert predicted.requires_grad
    assert predicted.item() == 1


@pytest.mark.parametrize("cap", ["max_coordinates", "max_atom_bytes"])
def test_evaluation_capacity_cannot_trigger_silent_target_omission(cap):
    old, reference, descriptor = metric_spaces()
    with pytest.raises(complete.FeatureCapacityError):
        complete.common_support_metrics(old, [[1]], [{"p": (descriptor, Counter(a=1, b=1))}],
            reference_space=reference, **{cap: 1})


def test_reference_must_include_every_model_coordinate_and_projection():
    old, reference, descriptor = metric_spaces()
    old["columns"] = [["p", "outside"]]
    with pytest.raises(ValueError, match="outside"):
        complete.common_support_metrics(old, [[1]], [{"p": (descriptor, Counter(a=1))}], reference_space=reference)
    old["columns"] = [["p", "a"]]
    with pytest.raises(ValueError, match="unexpected projection"):
        complete.common_support_metrics(old, [[1]], [{"q": (descriptor, Counter(a=1))}], reference_space=reference)


def test_oversized_atom_counts_rejected_before_log_or_memory_work():
    old, reference, descriptor = metric_spaces()
    with pytest.raises(ValueError, match="positive integers"):
        complete.common_support_metrics(old, [[1]],
            [{"p": (descriptor, Counter(a=10**1000))}], reference_space=reference)


def test_uneven_projection_presence_matches_existing_masked_objective():
    import torch
    _, reference, descriptor = metric_spaces()
    reference["projections"].update(q={**descriptor, "logic_family": "deontic"},
        r={**descriptor, "logic_family": "temporal"})
    reference["columns"].extend([["q", "a"], ["r", "a"]])
    rows = [{"p": (descriptor, Counter(a=1))},
        {"q": (reference["projections"]["q"], Counter(a=1))}]
    # Arbitrary outputs in absent projections must not become false positives.
    predicted = torch.tensor([[.5, 0, 999, 999], [999, 999, .25, 999]], dtype=torch.float64)
    target, mask, spans, _ = original._matrix(reference, rows)
    expected, metrics = original._objective(torch, predicted, target, mask, spans, reference["projections"])
    scored = complete.common_support_metrics(reference, predicted, rows, reference_space=reference)
    assert scored["objective"] == pytest.approx(float(expected), abs=1e-15)
    assert scored["families"] == pytest.approx(metrics["families"], abs=1e-15)
    assert set(scored["projections"]) == {"p", "q"}
    assert scored["coverage"]["emitted_projection_occurrences"] == 2
    assert scored["coverage"]["absent_projection_ids"] == ["r"]
    assert scored["coverage"]["absent_projections_by_row"] == [
        {"row": 0, "projection_ids": ["q", "r"]}, {"row": 1, "projection_ids": ["p", "r"]}]
    assert scored["coverage"]["all_emitted_projections_have_loss"] is True
    assert all(row["rows"] == 1 for row in scored["projections"].values())
