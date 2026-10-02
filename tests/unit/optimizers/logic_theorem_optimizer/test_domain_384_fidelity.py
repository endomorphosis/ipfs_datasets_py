"""Exact full-value weighting and generated-output fidelity without teacher forcing."""
from copy import deepcopy
import json

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_384_autoencoder as baseline
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_384_fidelity as subject


def atom():
    return {"kind": "intent_rich_ast", "document": {
        "kind": "atom", "actor": "curator", "action": "verify",
        "object": "invoice", "modality": "required"}}


def ui():
    return {"kind": "ui_component", "document": {"component_id": "accept",
        "role": "link", "privacy_sensitivity": "none",
        "presentation_classification": "interactive"}}


def tokens(value):
    return baseline._tokens(value)


@pytest.mark.parametrize("value", [
    atom(), ui(),
    {"kind": "if", "guard": {"subject": "curator", "negated": False,
                               "property": "ready"}, "body": atom()["document"]},
    {"a/b~c": [None, False, True, 0, -2, 2.0, -0.0, 1e-12, "null", "true", "clé\n\"\\"],
     "empty": {"array": [], "object": {}}, "0": "numeric object key"},
    {}, [], None, False, 20, "root scalar",
])
def test_every_token_matches_baseline_codec_and_every_scalar_is_weighted(value):
    observed = subject.target_token_alignment(value)
    assert observed["tokens"] == tokens(value)
    assert observed["canonical_json"] == json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    assert "".join(observed["tokens"]) == observed["canonical_json"]
    for item in observed["alignment"]:
        assert item["weight"] == (4.0 if item["role"] == "scalar_value" else 1.0)
    scalar_rows = [row for row in observed["alignment"] if row["role"] == "scalar_value"]
    result = subject.evaluate_generated(value, observed["tokens"], ended=True)
    assert result["scalar_total"] == len(scalar_rows)
    assert result["scalar_correct"] == len(scalar_rows)
    assert result["exact"] is True
    assert result["proof_authority"] is False


def test_json_pointer_paths_disambiguate_keys_array_indices_and_string_values():
    target = {"a/b~c": [{"0": "a/b~c", "v": False}], "0": None}
    rows = subject.target_token_alignment(target)["alignment"]
    values = {row["path"]: row for row in rows if row["role"] == "scalar_value"}
    assert values["/a~1b~0c/0/0"]["path_segments"] == ["a/b~c", 0, "0"]
    assert values["/a~1b~0c/0/v"]["value_type"] == "boolean"
    assert values["/0"]["path_segments"] == ["0"]
    assert values["/0"]["value_type"] == "null"
    identical_text = [row for row in rows if row["token"] == '"a/b~c"']
    assert {row["role"] for row in identical_text} == {"key", "scalar_value"}


def test_teacher_forcing_weights_match_actual_shifted_batch_and_padding():
    torch = pytest.importorskip("torch")
    targets = [atom(), {"kind": "ui_component", "document": {"component_id": "a", "role": "button"}}]
    rows = [{"embedding": [0.] * 384, "target": target} for target in targets]
    vocabulary = [*baseline.SPECIAL, *sorted({token for target in targets for token in tokens(target)})]
    _, batch = baseline._batch(torch, rows, vocabulary, 64)
    for index, target in enumerate(targets):
        labels = batch[index, 1:].tolist()
        weights = subject.teacher_forcing_weights(target, width=len(labels), scalar_value_weight=7)
        alignment = subject.target_token_alignment(target, scalar_value_weight=7)
        assert [vocabulary[label] for label in labels[:len(alignment["tokens"])]] == alignment["tokens"]
        assert weights[:len(alignment["tokens"])] == alignment["weights"]
        assert labels[len(alignment["tokens"])] == 2
        assert weights[len(alignment["tokens"])] == 1
        assert all(weight == 0 for label, weight in zip(labels, weights) if label == 0)
        assert all(weight > 0 for label, weight in zip(labels, weights) if label != 0)
    with pytest.raises(ValueError, match="omit"):
        subject.teacher_forcing_weights(atom(), width=len(tokens(atom())))


@pytest.mark.parametrize("weight", [0, -1, .9, 101, float("nan"), float("inf"), True, "4"])
def test_invalid_weight_never_disables_structure_or_values(weight):
    with pytest.raises(ValueError, match="scalar_value_weight"):
        subject.target_token_alignment(atom(), scalar_value_weight=weight)


@pytest.mark.parametrize("target", [{1: "coerced key"}, {"x": (1,)}, {"x": float("nan")},
                                    {"x": float("inf")}, {"x": b"bytes"}])
def test_non_json_or_nonfinite_targets_fail_closed(target):
    with pytest.raises(ValueError):
        subject.target_token_alignment(target)


def test_cyclic_deep_oversize_and_excessive_token_targets_fail_before_allocation():
    cyclic = []
    cyclic.append(cyclic)
    with pytest.raises(ValueError, match="cyclic"):
        subject.target_token_alignment(cyclic)
    deep = []
    for _ in range(66):
        deep = [deep]
    with pytest.raises(ValueError, match="depth"):
        subject.target_token_alignment(deep)
    with pytest.raises(ValueError, match="byte bound"):
        subject.target_token_alignment({str(i): "x" * 32768 for i in range(8)})
    with pytest.raises(ValueError, match="token bound"):
        subject.target_token_alignment([0] * 512)


@pytest.mark.parametrize("changed,path", [
    ({"negated": 0, "count": 1, "values": ["first", "second"], "unset": None}, "/negated"),
    ({"negated": False, "count": 1.0, "values": ["first", "second"], "unset": None}, "/count"),
    ({"negated": False, "count": 1, "values": ["second", "first"], "unset": None}, "/values/0"),
    ({"negated": False, "count": 1, "values": ["first", "second"]}, "/unset"),
])
def test_exact_comparison_preserves_types_array_order_and_null_presence(changed, path):
    expected = {"negated": False, "count": 1, "values": ["first", "second"], "unset": None}
    report = subject.evaluate_generated(expected, tokens(changed), ended=True)
    assert report["exact"] is False
    assert report["scalar_total"] == 5
    assert any(row["path"] == path and not row["correct"] for row in report["per_path"])
    assert report["scalar_correct"] < report["scalar_total"]


def test_extra_fields_are_reported_and_reduce_precision_not_hidden_in_recall():
    report = subject.evaluate_generated({"x": 1}, tokens({"x": 1, "extra": True}), ended=True)
    assert report["scalar_value_accuracy"] == 1
    assert report["scalar_value_precision"] == .5
    assert report["exact"] is False
    assert report["differences"][0]["kind"] == "extra_field"


@pytest.mark.parametrize("generated,ended,status", [
    ([], False, "incomplete_generation"),
    (['{', '"x"', ':', '1', '}'], False, "incomplete_generation"),
    ([], True, "invalid_token_sequence"),
    (["<eos>"], True, "invalid_token_sequence"),
    (["1 2"], True, "invalid_token_sequence"),
    (['{', '"x"', ':', '1', ',', '"x"', ':', '2', '}'], True, "invalid_generated_json"),
    (['{', '"x"', ':', '}'], True, "invalid_generated_json"),
    (["1e999"], True, "invalid_generated_json"),
    (["NaN"], True, "invalid_token_sequence"),
    (['"\ud800"'], True, "invalid_token_sequence"),
    (["true"], 1, "invalid_generation_metadata"),
])
def test_invalid_generation_retains_all_expected_fields_and_zero_credit(generated, ended, status):
    report = subject.evaluate_generated(atom(), generated, ended=ended, domain_id="intent_ir")
    assert report["generation"]["status"] == status
    assert report["generation"]["candidate"] is None
    assert report["scalar_total"] == 6
    assert report["scalar_correct"] == 0
    assert report["native_valid"] is False
    assert report["exact"] is False
    assert all(row["correct"] is False for row in report["per_path"])


@pytest.mark.parametrize("domain,target", [("intent_ir", atom()), ("ui_ux_ir", ui())])
def test_native_valid_matches_stay_unqualified_and_invalid_native_gets_no_partial_credit(domain, target):
    exact = subject.evaluate_generated(target, tokens(target), ended=True, domain_id=domain)
    assert exact["exact"] is True and exact["native_valid"] is True
    assert exact["scalar_correct"] == exact["scalar_total"]
    assert not exact["admitted"] and not exact["source_semantics_verified"]
    changed = deepcopy(target)
    changed["document"]["unexpected_field"] = "must not disappear"
    bad = subject.evaluate_generated(target, tokens(changed), ended=True, domain_id=domain)
    assert bad["native_validation"]["status"] == "native_invalid"
    assert bad["native_valid"] is False and bad["exact"] is False
    assert bad["scalar_correct"] == 0
    assert all(row["raw_typed_value_equal"] for row in bad["fields"])
    assert not any(row["correct"] for row in bad["fields"])


def test_semantic_modality_and_ui_role_errors_are_measured_even_when_native_valid():
    changed = atom()
    changed["document"]["modality"] = "prohibited"
    report = subject.evaluate_generated(atom(), tokens(changed), ended=True, domain_id="intent_ir")
    assert report["native_valid"] is True and report["exact"] is False
    assert report["scalar_correct"] == 5
    assert [row["path"] for row in report["per_path"] if not row["correct"]] == ["/document/modality"]
    changed_ui = ui()
    changed_ui["document"]["role"] = "button"
    report = subject.evaluate_generated(ui(), tokens(changed_ui), ended=True, domain_id="ui_ux_ir")
    assert report["native_valid"] is True and report["exact"] is False
    assert [row["path"] for row in report["critical_fields"] if not row["correct"]] == ["/document/role"]


def test_critical_subset_cannot_hide_other_field_errors_or_change_generated_output():
    expected, actual = atom(), atom()
    actual["document"]["actor"] = "reviewer"
    generated = tokens(actual)
    report = subject.evaluate_generated(expected, generated, ended=True, domain_id="intent_ir",
                                         critical_paths=["/document/modality"])
    assert report["critical_fields_exact"] is True
    assert report["exact"] is False and report["scalar_correct"] == 5
    assert report["generation"]["candidate"] == actual
    assert subject.parse_generated(generated, ended=True)["candidate"] == actual
    assert report["target_used_for_generation"] is False
    with pytest.raises(ValueError, match="expected scalar"):
        subject.evaluate_generated(expected, generated, ended=True, critical_paths=["/document"])


def test_expected_invalid_native_schema_is_a_reference_error_not_successful_prediction():
    expected = atom()
    expected["document"]["modality"] = "invented"
    with pytest.raises(ValueError, match="declared modality"):
        subject.evaluate_generated(expected, tokens(expected), ended=True, domain_id="intent_ir")


def test_no_implicit_cast_between_numeric_object_keys_and_array_indices():
    expected, actual = {"x": {"0": True}}, {"x": [True]}
    report = subject.evaluate_generated(expected, tokens(actual), ended=True)
    assert report["scalar_correct"] == 0
    assert report["per_path"][0]["path_segments"] == ["x", "0"]
    assert report["exact"] is False


@pytest.mark.parametrize("field,value", [("privacy_sensitivity", "interactive"),
                                        ("presentation_classification", "restricted")])
def test_ui_cross_field_vocabulary_is_native_invalid_with_no_partial_credit(field, value):
    expected, candidate = ui(), ui()
    candidate["document"][field] = value
    # Demonstrate the old envelope boundary so this cannot regress to it.
    assert baseline.validate_target("ui_ux_ir", candidate)["valid"] is True
    with pytest.raises(ValueError, match="closed vocabulary"):
        subject.validate_native_target("ui_ux_ir", candidate)
    report = subject.evaluate_generated(expected, tokens(candidate), ended=True, domain_id="ui_ux_ir")
    assert report["native_validation"]["status"] == "native_invalid"
    assert report["native_valid"] is False
    assert report["exact"] is False and report["scalar_correct"] == 0
    assert report["scalar_total"] == 5
    assert sum(row["raw_typed_value_equal"] for row in report["fields"]) == 4
    with pytest.raises(ValueError, match="closed vocabulary"):
        subject.evaluate_generated(candidate, tokens(candidate), ended=True, domain_id="ui_ux_ir")


def test_stronger_ui_validation_preserves_complete_rich_document_and_scope():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / "logic/ui_ux_ir/test_schema.py"
    spec = importlib.util.spec_from_file_location("_ui_semantic_fidelity_fixtures", path)
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    expected = fixtures._rich_document().to_dict()
    validated = subject.validate_native_target("ui_ux_ir", expected)
    assert validated["canonical_ir"] == expected
    assert validated["native_ir"] == expected
    assert len(expected) == 44
    assert validated["semantic_validation"]["valid"] is True
    assert validated["semantic_validation"]["scope"] == "document_component_graph"
    assert validated["semantic_validation"]["source_semantics_verified"] is False
    assert validated["semantic_validation"]["proof_authority"] is False
    assert validated["source_semantics_verified"] is False


def test_stronger_ui_fragment_gate_retains_original_target_with_local_scope():
    target = ui()
    validated = subject.validate_native_target("ui_ux_ir", target)
    assert validated["canonical_ir"] == target
    assert validated["semantic_validation"]["scope"] == "local_component_fragment"
    assert subject.validate_native_target("intent_ir", atom())["semantic_validation"] is None
