"""Inert geometry and scalar-oracle tests; no Torch, model, fit or statutory gold."""
import ast
import builtins
import copy
import importlib
import itertools
import math
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.legal_ir import structured_span_objective as subject


def record(*, optional=()):
    words = ["actor", "action", "object", "condition", "exception", "time"]
    tokens, cursor = [], 0
    for text in words:
        tokens.append({"text": text, "start": cursor, "end": cursor + len(text),
                       "byte_ids": [value + 1 for value in text.encode("utf-8")]})
        cursor += len(text) + 1
    presence = [True, True, *[field in optional for field in subject.OPTIONAL_FIELDS]]
    return {"tokens": tokens, "latent": [],
            "labels": {"modality": 0, "presence": presence,
                       "spans": [(index, index) if present else (-100, -100)
                                 for index, present in enumerate(presence)]}}


def scores(count=2):
    return [[0.0] * count for _ in subject.FIELDS]


def brute_force_overlap(start_left, end_left, start_right, end_right):
    def distribution(start, end):
        intervals = [(left, right, math.exp(start[left] + end[right]))
                     for left in range(len(start)) for right in range(left, len(start))]
        denominator = sum(value for _, _, value in intervals)
        return [(left, right, value / denominator) for left, right, value in intervals]
    return sum(p_left * p_right
               for left, right, p_left in distribution(start_left, end_left)
               for other_left, other_right, p_right in distribution(start_right, end_right)
               if max(left, other_left) <= min(right, other_right))


def test_geometry_is_closed_and_does_not_claim_source_replay_or_review():
    rows = [record(optional=("conditions",))]
    before = copy.deepcopy(rows)
    result = subject.reference_geometry(rows)
    assert rows == before
    assert result["row_count"] == 1 and result["padded_token_count"] == 6
    assert result["rows"][0]["active_fields"] == ["actor", "action", "conditions"]
    assert result["rows"][0]["active_field_pairs"] == [[0, 1], [0, 3], [1, 3]]
    assert result["provided_label_geometry_valid"] is True
    assert result["full_source_bytes_replayed"] is False
    assert all(result[key] is False for key in ("semantic_gold", "qualified", "proof_authority", "source_semantics_verified"))


@pytest.mark.parametrize("optional", [(), ("object",), ("conditions", "temporal"), tuple(subject.OPTIONAL_FIELDS)])
def test_optional_reference_presence_controls_geometry(optional):
    result = subject.reference_geometry([record(optional=optional)])["rows"][0]
    assert len(result["active_fields"]) == 2 + len(optional)
    assert len(result["active_field_pairs"]) == math.comb(2 + len(optional), 2)


@pytest.mark.parametrize("field", [0, 1])
def test_required_reference_roles_cannot_be_masked_away(field):
    row = record()
    row["labels"]["presence"][field] = False
    row["labels"]["spans"][field] = (-100, -100)
    with pytest.raises(ValueError, match="actor and action"):
        subject.reference_geometry([row])


@pytest.mark.parametrize("value", [0, 1, None, "true", []])
def test_reference_presence_requires_boolean_values(value):
    row = record()
    row["labels"]["presence"][2] = value
    with pytest.raises(ValueError, match="six boolean"):
        subject.reference_geometry([row])


@pytest.mark.parametrize("interval", [(0, 0), (-100, 0), (0, -100), (True, True)])
def test_absent_reference_spans_must_be_explicit(interval):
    row = record()
    row["labels"]["spans"][2] = interval
    with pytest.raises(ValueError):
        subject.reference_geometry([row])


@pytest.mark.parametrize("interval", [(-1, 0), (1, 0), (0, 6), (True, 1)])
def test_present_reference_interval_bounds(interval):
    row = record()
    row["labels"]["spans"][0] = interval
    with pytest.raises(ValueError):
        subject.reference_geometry([row])


def test_overlapping_authored_reference_intervals_are_rejected():
    row = record()
    row["labels"]["spans"][0] = (0, 1)
    with pytest.raises(ValueError, match="intervals overlap"):
        subject.reference_geometry([row])


@pytest.mark.parametrize("change", ["record_extra", "labels_extra", "token_extra", "bad_bytes", "bad_offset", "bad_modality", "bad_latent"])
def test_closed_internal_geometry_rejects_changes(change):
    row = record()
    if change == "record_extra":
        row["teacher"] = True
    elif change == "labels_extra":
        row["labels"]["gold"] = True
    elif change == "token_extra":
        row["tokens"][0]["teacher"] = True
    elif change == "bad_bytes":
        row["tokens"][0]["byte_ids"] = [1]
    elif change == "bad_offset":
        row["tokens"][1]["start"] = 0
    elif change == "bad_modality":
        row["labels"]["modality"] = True
    else:
        row["latent"] = [float("nan")] * 384
    with pytest.raises(ValueError):
        subject.reference_geometry([row])


@pytest.mark.parametrize("rows", [[], [record()] * 33, None, {}])
def test_batch_bounds(rows):
    with pytest.raises(ValueError, match="one to 32"):
        subject.reference_geometry(rows)


def test_token_bounds_are_not_truncated():
    row = record()
    row["tokens"] = row["tokens"] * 43
    with pytest.raises(ValueError, match="one to 256"):
        subject.reference_geometry([row])


def test_zero_latent_and_raw384_latent_are_explicitly_supported():
    source = record()
    raw = record()
    raw["latent"] = [0.0] * 384
    assert subject.reference_geometry([source, raw])["row_count"] == 2


def test_uniform_two_token_order_and_overlap_hand_calculation():
    start, end = scores(), scores()
    result = subject.probability_reference(start, end, [True, True, False, False, False, False])
    # Each field has three equally weighted valid intervals:00,01,11.
    # Only two of their nine pairings are disjoint.
    assert result["valid_order_mass"]["actor"] == pytest.approx(3 / 4)
    assert result["order_loss"] == pytest.approx(-math.log(3 / 4))
    assert result["overlap_loss"] == pytest.approx(7 / 9)
    assert result["unweighted_structure"] == pytest.approx((-math.log(3 / 4) + 7 / 9) / 2)


@pytest.mark.parametrize("count", [1, 2, 3, 7])
def test_uniform_order_mass_matches_triangular_interval_count(count):
    result = subject.probability_reference(scores(count), scores(count), [True, True, False, False, False, False])
    assert result["valid_order_mass"]["actor"] == pytest.approx((count + 1) / (2 * count))
    assert 0 <= result["overlap_loss"] <= 1


def test_one_token_oracle_has_overlap_one_without_admitting_invalid_reference_roles():
    result = subject.probability_reference(scores(1), scores(1), [True, True, False, False, False, False])
    assert result["order_loss"] == pytest.approx(0)
    assert result["overlap_loss"] == pytest.approx(1)
    row = record()
    row["tokens"] = row["tokens"][:1]
    row["labels"]["spans"][1] = (0, 0)
    with pytest.raises(ValueError, match="intervals overlap"):
        subject.reference_geometry([row])


@pytest.mark.parametrize("optional_count", [0, 1, 2, 4])
def test_overlap_cdf_matches_exhaustive_interval_pairs(optional_count):
    start = [[-0.4 * field + token / 3 for token in range(4)] for field in range(6)]
    end = [[0.2 * field - token / (field + 2) for token in range(4)] for field in range(6)]
    presence = [True, True, *[field < optional_count for field in range(4)]]
    result = subject.probability_reference(start, end, presence)
    active = [field for field, present in enumerate(presence) if present]
    expected = []
    for left, right in itertools.combinations(active, 2):
        value = brute_force_overlap(start[left], end[left], start[right], end[right])
        expected.append(value)
    assert [row["overlap_probability"] for row in result["field_pairs"]] == pytest.approx(expected)
    assert result["overlap_loss"] == pytest.approx(sum(expected) / len(expected))


def test_absent_pointer_scores_do_not_affect_structure():
    start, end = scores(3), scores(3)
    presence = [True, True, False, False, False, False]
    baseline = subject.probability_reference(start, end, presence)
    for field in range(2, 6):
        start[field] = [100, -100, 0]
        end[field] = [-90, 90, 1]
    assert subject.probability_reference(start, end, presence) == baseline


def test_separated_confident_point_spans_have_small_overlap():
    start, end = scores(3), scores(3)
    start[0] = end[0] = [30, -30, -30]
    start[1] = end[1] = [-30, -30, 30]
    result = subject.probability_reference(start, end, [True, True, False, False, False, False])
    assert result["order_loss"] < 1e-12
    assert result["overlap_loss"] < 1e-12


def test_invalid_order_heads_have_positive_stable_log_mass_loss():
    start, end = scores(2), scores(2)
    start[0], end[0] = [-1000, 1000], [1000, -1000]
    result = subject.probability_reference(start, end, [True, True, False, False, False, False])
    assert math.isfinite(result["order_loss"]) and result["order_loss"] > 900
    assert result["valid_order_mass"]["actor"] == 0


def test_extreme_finite_float32_scores_remain_finite_in_oracle():
    start, end = scores(2), scores(2)
    start[0], end[0] = [-3e38, 3e38], [3e38, -3e38]
    result = subject.probability_reference(start, end, [True, True, False, False, False, False])
    assert math.isfinite(result["order_loss"])
    assert 0 <= result["overlap_loss"] <= 1


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "1", 4e38])
def test_oracle_refuses_invalid_pointer_values(value):
    start, end = scores(), scores()
    start[0][0] = value
    with pytest.raises(ValueError, match="finite matched"):
        subject.probability_reference(start, end, [True, True, False, False, False, False])


@pytest.mark.parametrize("weight", [True, float("nan"), float("inf"), -0.1, 1.1, "0.1"])
def test_objective_refuses_bad_weight_before_numerical_backend_access(weight):
    with pytest.raises(ValueError, match="structure_weight"):
        subject.objective_from_output(object(), {}, [], structure_weight=weight)


def test_objective_refuses_bad_reference_before_numerical_backend_access():
    with pytest.raises(ValueError, match="one to 32"):
        subject.objective_from_output(object(), {}, [])


def test_import_geometry_and_scalar_oracle_never_import_numerical_backends(monkeypatch):
    original = builtins.__import__
    def refuse(name, *args, **kwargs):
        assert name.split(".")[0] not in {"torch", "numpy", "transformers", "sentence_transformers"}
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", refuse)
    module = importlib.reload(subject)
    assert module.reference_geometry([record()])["row_count"] == 1
    assert module.probability_reference(scores(), scores(), [True, True, False, False, False, False])["qualified"] is False


def test_objective_has_no_model_open_forward_or_optimizer_call():
    tree = ast.parse(Path(subject.__file__).read_text())
    imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert all(not any(name.name.split(".")[0] in {"torch", "numpy", "transformers", "sentence_transformers"}
                       for name in node.names) for node in imports)
    forbidden = {"forward", "backward", "step", "zero_grad", "load_checkpoint", "open", "decode_formal_logic"}
    assert not [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute) and node.func.attr in forbidden]
