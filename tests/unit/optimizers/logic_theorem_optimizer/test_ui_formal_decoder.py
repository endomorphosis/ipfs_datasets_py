"""Exact five-projection structural readout; no learned source-decoder claim."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import ui_formal_decoder as decoder
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import ui_feature_training as ui
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location("_ui_binding_decoder_fixtures",
    ROOT / "tests/unit/logic/formalization/autoencoder/test_ui_training_inputs.py")
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


def case():
    rows = [fixtures.native_row(i) for i in (1, 2)]
    targets = [decoder.inputs.prepare_ui_training_row(row).target for row in rows]
    space = decoder.features.build_feature_space("ui_ux_ir", ui.DEFAULT_PROJECTIONS, targets)
    return space, targets


def oracle(space, targets):
    matrix, sources, coverage = decoder.features._matrix(space, targets)
    return {"schema": "native-projection-feature-inference/v1", "feature_space_sha256": decoder.features.digest(space),
        "state_sha256": "a" * 64, "training_executed": False, "coverage": coverage, **decoder.features.FALSE,
        "rows": [{"source_digest": source, "latent": [], "reconstructed_projection_features": {
            name: [value for (projection, _), value in zip(space["columns"], row) if projection == name]
            for name in space["projection_ids"]}} for source, row in zip(sources, matrix)]}


def test_perfect_coordinates_restore_all_five_original_projections_without_targets_at_decode():
    space, targets = case()
    head = decoder.train_ui_formal_decoder(space, targets)
    scores = oracle(space, targets)
    old = decoder.base.decode_formal_features(space, head["base_head"], scores)
    assert all(next(p for p in row["projections"] if p["projection_id"] == decoder.inputs.INTERFACE_PROJECTION)
               ["status"] == "abstained" for row in old["rows"])
    result = decoder.decode_ui_formal_features(space, head, scores)
    assert result["decoded_projection_count"] == 10
    assert result["decoded_native_record_count"] == 10
    assert result["decoded_backend_formula_count"] == 0
    assert result["decoded_formulas_generated"] is False
    assert not result["independent_text_to_logic"] and not result["trained_neural_decoder"]
    for predicted, target in zip(result["rows"], targets):
        expected = {p["projection_id"]: p["expression"] for p in target.to_dict()["projections"]}
        assert all(p["expression"] == expected[p["projection_id"]] for p in predicted["projections"])
        interface = next(p for p in predicted["projections"] if p["projection_id"] == decoder.inputs.INTERFACE_PROJECTION)
        assert interface["interface_preimage_status"] == "unknown_missing_complete_descriptor"
        assert interface["runtime_authenticity_status"] == "unknown_without_observation"
        assert json.loads(interface["readable_notation"]) == interface["expression"]
        assert interface["family_syntax_checked"] is False and interface["source_semantics_verified"] is False
    fidelity = decoder.evaluate_ui_decoded_fidelity(space, head, scores, targets)
    assert fidelity["projection_count"] == fidelity["exact_projection_count"] == 10
    assert fidelity["abstained_projection_count"] == 0


def test_interface_only_success_never_reports_a_backend_formula():
    space, targets = case()
    head = decoder.train_ui_formal_decoder(space, targets)
    scores = oracle(space, targets)
    for row in scores["rows"]:
        for name, values in row["reconstructed_projection_features"].items():
            if name != decoder.inputs.INTERFACE_PROJECTION:
                row["reconstructed_projection_features"][name] = [0.0] * len(values)
    result = decoder.decode_ui_formal_features(space, head, scores)
    assert result["status"] == "partial"
    assert result["decoded_projection_count"] == result["decoded_native_record_count"] == 2
    assert result["decoded_backend_formula_count"] == 0
    assert result["decoded_formulas_generated"] is False
    assert all(p["family_syntax_checked"] is False for row in result["rows"] for p in row["projections"])


@pytest.mark.parametrize("value", [0.0, -1.0])
def test_zero_and_negative_scores_abstain_without_expected_target_fallback(value):
    space, targets = case()
    head = decoder.train_ui_formal_decoder(space, targets)
    scores = oracle(space, targets)
    for row in scores["rows"]:
        for name, values in row["reconstructed_projection_features"].items():
            row["reconstructed_projection_features"][name] = [value] * len(values)
    result = decoder.decode_ui_formal_features(space, head, scores)
    fidelity = decoder.evaluate_ui_decoded_fidelity(space, head, scores, targets)
    assert result["decoded_projection_count"] == fidelity["exact_projection_count"] == 0
    assert fidelity["projection_count"] == fidelity["abstained_projection_count"] == 10
    assert all(row["difference_count"] for row in fidelity["rows"])


@pytest.mark.parametrize("mutation", ["extra", "wrong_cid", "method_join", "unknown_risk", "streaming",
    "remote_ref", "schema_type", "ambiguous_join", "missing_schema_field"])
def test_interface_native_schema_mismatches_fail_closed(mutation):
    space, targets = case()
    expression = next(p["expression"] for p in targets[0].to_dict()["projections"]
                      if p["projection_id"] == decoder.inputs.INTERFACE_PROJECTION)
    row = expression["bindings"][0]
    if mutation == "extra": row["unknown"] = "invented"
    elif mutation == "wrong_cid": row["interface_cid"] = "bafy-mock"
    elif mutation == "method_join": row["method_name"] = "other_method"
    elif mutation == "unknown_risk": row["risk_class"] = "very_safe"
    elif mutation == "streaming": row["method_contract"]["streaming"] = True
    elif mutation == "remote_ref": row["method_contract"]["output_schema"]["$ref"] = "https://example.invalid/schema"
    elif mutation == "schema_type": row["method_contract"]["output_schema"]["type"] = "not_a_type"
    elif mutation == "ambiguous_join": expression["bindings"].append(deepcopy(row))
    else: del row["method_contract"]["input_schema"]
    with pytest.raises(ValueError):
        decoder.validate_interface_expression(space["projections"][decoder.inputs.INTERFACE_PROJECTION], expression)


@pytest.mark.parametrize("expected,actual", [
    ({"negated": True}, {"negated": False}),
    ({"negated": True}, {"negated": 1}),
    ({"argument_type": "integer"}, {"argument_type": "number"}),
    ({"required": ["user", "token"]}, {"required": ["token", "user"]}),
    ({"effects": ["confirm", "send"]}, {"effects": ["send", "confirm"]}),
    ({"actor": "Alice", "object": "Config.YAML"}, {"actor": "alice", "object": "config.yaml"}),
    ({"guard": "consent", "action": "submit"}, {"action": "submit"}),
    ({"value": 1}, {"value": 1.0}),
])
def test_fidelity_counts_types_negation_order_and_missing_slots(expected, actual):
    measured = decoder.typed_fidelity(expected, actual)
    assert measured["exact"] is False and measured["difference_count"] > 0
    assert measured["expected_sha256"] != measured["actual_sha256"]


def test_fidelity_target_source_identity_and_order_cannot_be_reassigned():
    space, targets = case()
    head = decoder.train_ui_formal_decoder(space, targets)
    with pytest.raises(ValueError, match="source order"):
        decoder.evaluate_ui_decoded_fidelity(space, head, oracle(space, targets), list(reversed(targets)))


def test_versioned_head_cannot_change_domain_producers_or_authority():
    space, targets = case()
    head = decoder.train_ui_formal_decoder(space, targets)
    for key, value in (("version", "legacy_v1"), ("producer_pins", {}),
                       ("new_neural_decoder_trained", True), ("independent_text_to_logic", True)):
        changed = deepcopy(head); changed[key] = value
        with pytest.raises(ValueError):
            decoder.validate_ui_decoder(space, changed)


def test_actual_train_registry_reopen_decoder_inference_and_resume(tmp_path):
    pytest.importorskip("torch")
    train = [fixtures.native_row(i, group_id=f"train:{i}") for i in (1, 2)]
    tune = [fixtures.native_row(i, group_id=f"tune:{i}", split="validation") for i in (3, 4)]
    with AutoencoderRegistry(tmp_path / "weights.duckdb", tmp_path / "artifacts") as registry:
        result = ui.train_ui_feature_batch(registry, train, tune, tmp_path / "first", epochs=8,
            formal_decoder_version=decoder.VERSION)
        version = result["registration"]["version_id"]
        assert result["decoder_tuning_fidelity"]["projection_count"] == 10
        assert result["formal_decoder_version"] == decoder.VERSION
    with AutoencoderRegistry(tmp_path / "weights.duckdb", tmp_path / "artifacts") as registry:
        inferred = ui.infer_ui_feature_batch(registry, version, train, tmp_path / "inference")
        assert inferred["formal_decoding"]["decoder_version"] == decoder.VERSION
        interfaces = [p for row in inferred["formal_decoding"]["rows"] for p in row["projections"]
                      if p["projection_id"] == decoder.inputs.INTERFACE_PROJECTION]
        assert all(p["status"] == "decoded_candidate" for p in interfaces)
        assert inferred["decoder_fidelity"]["projection_count"] == 10
        assert inferred["training_executed"] is False and inferred["qualified"] is False
        artifact = registry.get_version(version)["artifact"]
        original = registry.artifact_path(artifact).read_bytes()
        resumed = ui.train_ui_feature_batch(registry, [fixtures.native_row(5)], tune, tmp_path / "resume",
            parent_version_id=version, epochs=1, formal_decoder_version=decoder.VERSION)
        assert resumed["formal_decoder_version"] == decoder.VERSION
        assert registry.artifact_path(artifact).read_bytes() == original
        with pytest.raises(ValueError, match="decoder version changed"):
            ui.train_ui_feature_batch(registry, [fixtures.native_row(6)], tune, tmp_path / "bad-resume",
                parent_version_id=version, epochs=1)


def test_unknown_decoder_version_refuses_before_preparation(tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "prepare_ui_rows", lambda *a, **k: pytest.fail("invalid version reached source preparation"))
    with pytest.raises(ValueError, match="unknown UI formal decoder"):
        ui.train_ui_feature_batch(None, [], [], tmp_path / "bad", formal_decoder_version="source384")
