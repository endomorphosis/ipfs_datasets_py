"""Model-score inverses of authored native targets; no semantic admission."""
import copy
import hashlib
import importlib
import importlib.util
import os
from pathlib import Path
import sys

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features_v2 as streamed


PREFIX = "ipfs_datasets_py.optimizers.logic_theorem_optimizer"
ROOT = Path(features.__file__).resolve().parents[3]


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


if os.environ.get("NATIVE_FORMAL_DECODER_PATH"):
    decoder = _load(os.environ["NATIVE_FORMAL_DECODER_PATH"], PREFIX + ".native_formal_decoder")
else:
    decoder = importlib.import_module(PREFIX + ".native_formal_decoder")
fixtures = _load(ROOT / "tests/unit/optimizers/logic_theorem_optimizer/test_autoencoder_projection_features.py", "_decoder_native_fixtures")


def _case(domain):
    prepare = {"intent_ir": fixtures._intent, "security_ir": fixtures._security, "ui_ux_ir": fixtures._ui}[domain]
    targets = [prepare(1), prepare(2)]
    ids = [row["projection_id"] for row in targets[0].to_dict()["projections"] if row["logic_family"]]
    space = features.build_feature_space(domain, ids, targets)
    return space, targets


def _oracle(space, targets):
    """Perfect reconstruction coordinates test the deterministic inverse only."""
    matrix, sources, coverage = features._matrix(space, targets)
    return {"schema": "native-projection-feature-inference/" + space["schema"].rsplit("/", 1)[1],
        "feature_space_sha256": features.digest(space), "state_sha256": "a" * 64,
        "training_executed": False, "coverage": coverage, **features.FALSE,
        "rows": [{"source_digest": source, "latent": [], "reconstructed_projection_features": {
            name: [row[index] for index, (projection, _) in enumerate(space["columns"]) if projection == name]
            for name in space["projection_ids"]}} for row, source in zip(matrix, sources)]}


@pytest.mark.parametrize("domain", ("security_ir", "intent_ir", "ui_ux_ir"))
def test_exact_coordinate_inverse_restores_real_native_expressions_and_empty_containers(domain):
    space, targets = _case(domain)
    head = decoder.train_formal_decoder(space, iter(targets))
    assert head["trainable_parameter_count"] == 0 and not head["new_neural_decoder_trained"]
    receipt = _oracle(space, targets)
    result = decoder.decode_formal_features(space, head, receipt)
    assert result["status"] == "decoded", result
    assert result["coverage"] == receipt["coverage"]
    for actual, target in zip(result["rows"], targets):
        expected = {row["projection_id"]: row["expression"] for row in target.to_dict()["projections"]}
        for projection in actual["projections"]:
            assert projection["expression"] == expected[projection["projection_id"]]
            assert all(projection[key] is False for key in decoder._FALSE)
            assert projection["family_syntax_checked"] is False
            if domain == "security_ir":
                assert projection["typed_expression"]["interface"] == "TypedExpression@1"
                assert projection["readable_notation"] is None
            else:
                assert projection["readable_notation"]
    assert result["decoded_formulas_generated"] and result["source_input_conditioned"]
    assert not result["independent_text_to_logic"] and not result["trained_neural_decoder"]


def test_values_come_only_from_scores_not_saved_target_answers():
    space, targets = _case("intent_ir")
    head = decoder.train_formal_decoder(space, targets)
    assert "produce_fixture_1" not in features._raw(head).decode()
    first = _oracle(space, targets[:1])
    second = _oracle(space, targets[1:])
    changed = copy.deepcopy(first)
    changed["rows"][0]["reconstructed_projection_features"] = second["rows"][0]["reconstructed_projection_features"]
    original = decoder.decode_formal_features(space, head, first)
    altered = decoder.decode_formal_features(space, head, changed)
    assert original["rows"][0]["source_digest"] == altered["rows"][0]["source_digest"]
    assert original["rows"][0]["projections"] != altered["rows"][0]["projections"]
    assert "produce_fixture_2" in features._raw(altered).decode()


def test_unknown_atoms_remain_visible_and_missing_leaf_evidence_abstains():
    space, targets = _case("intent_ir")
    head = decoder.train_formal_decoder(space, targets)
    receipt = _oracle(space, [fixtures._intent(3)])
    assert sum(row["unknown_atoms"] for row in receipt["coverage"]) > 0
    result = decoder.decode_formal_features(space, head, receipt)
    assert result["coverage"] == receipt["coverage"]
    row = next(item for item in result["rows"][0]["projections"] if item["projection_id"] == "intent-route/intentions/v1")
    assert row["status"] == "abstained"
    assert row["reason"] == "nonpositive_or_insufficient_leaf_score"


def test_zero_negative_and_tied_scores_abstain_without_target_fallback():
    space, targets = _case("intent_ir")
    head = decoder.train_formal_decoder(space, targets)
    for number in (0.0, -1.0):
        receipt = _oracle(space, targets[:1])
        for name, values in receipt["rows"][0]["reconstructed_projection_features"].items():
            receipt["rows"][0]["reconstructed_projection_features"][name] = [number] * len(values)
        result = decoder.decode_formal_features(space, head, receipt)
        assert result["status"] == "abstained" and not result["decoded_formulas_generated"]
        assert all(row["expression"] is None for row in result["rows"][0]["projections"])
    receipt = _oracle(space, targets[:1])
    name = "intent-route/intentions/v1"
    receipt["rows"][0]["reconstructed_projection_features"][name] = [1.0] * len(receipt["rows"][0]["reconstructed_projection_features"][name])
    result = decoder.decode_formal_features(space, head, receipt)
    assert next(row for row in result["rows"][0]["projections"] if row["projection_id"] == name)["reason"] == "ambiguous_leaf_scores"


def test_variable_shapes_remain_explicitly_unsupported():
    space, targets = _case("ui_ux_ir")
    raw = targets[1].to_dict()
    raw["projections"][0]["expression"]["facts"].append({"predicate": "ui_component", "args": ["extra", "button"], "source_ref_ids": []})
    from ipfs_datasets_py.logic.formalization.autoencoder.domain_targets import DomainTargetEnvelope
    targets[1] = DomainTargetEnvelope.from_dict(raw)
    space = features.build_feature_space("ui_ux_ir", space["projection_ids"], targets)
    head = decoder.train_formal_decoder(space, targets)
    assert head["projections"]["ui_ux_ir:flogic"]["status"] == "unsupported"
    result = decoder.decode_formal_features(space, head, _oracle(space, targets[:1]))
    row = next(item for item in result["rows"][0]["projections"] if item["projection_id"] == "ui_ux_ir:flogic")
    assert row["reason"] == "variable_shape_requires_presence_head" and row["expression"] is None


def test_head_identity_shape_authority_and_training_provenance_fail_closed():
    space, targets = _case("ui_ux_ir")
    head = decoder.train_formal_decoder(space, targets)
    for key, value in (("implementation_sha256", "0" * 64), ("feature_space_sha256", "0" * 64),
                       ("qualified", True), ("validator_sources", {}), ("score_policy", {"minimum_score": -100, "minimum_margin": 0})):
        changed = copy.deepcopy(head); changed[key] = value
        with pytest.raises(decoder.FormulaDecoderError):
            decoder.validate_decoder(space, changed)
    changed = copy.deepcopy(head)
    changed["projections"]["ui_ux_ir:flogic"]["shape"] = {"kind": "leaf", "path": ["invented"]}
    with pytest.raises(decoder.FormulaDecoderError, match="path"):
        decoder.validate_decoder(space, changed)
    with pytest.raises(decoder.FormulaDecoderError, match="targets differ"):
        decoder.train_formal_decoder(space, list(reversed(targets)))
    receipt = _oracle(space, targets[:1])
    receipt["rows"][0]["reconstructed_projection_features"]["ui_ux_ir:flogic"][0] = float("nan")
    with pytest.raises(decoder.FormulaDecoderError, match="score vector"):
        decoder.decode_formal_features(space, head, receipt)


def test_incoherent_predicted_security_identity_is_not_repaired():
    space, targets = _case("security_ir")
    head = decoder.train_formal_decoder(space, targets)
    receipt, other = _oracle(space, targets[:1]), _oracle(space, targets[1:])
    name = space["projection_ids"][0]
    columns = [token for projection, token in space["columns"] if projection == name]
    for index, token in enumerate(columns):
        import json
        if json.loads(token)[0] == ["program_id"]:
            receipt["rows"][0]["reconstructed_projection_features"][name][index] = other["rows"][0]["reconstructed_projection_features"][name][index]
    result = decoder.decode_formal_features(space, head, receipt)
    assert result["status"] == "abstained"
    assert result["rows"][0]["projections"][0]["reason"] == "decoded_native_validation_failed"


@pytest.mark.parametrize("domain", ("security_ir", "intent_ir", "ui_ux_ir"))
def test_real_trained_weights_feed_decoder_and_zero_weight_control_abstains(domain):
    prepare = {"intent_ir": fixtures._intent, "security_ir": fixtures._security, "ui_ux_ir": fixtures._ui}[domain]
    train, tune = [prepare(1)], [prepare(2)]
    projection = {"intent_ir": "intent-route/norms/v1", "security_ir": "program.program_ir/v1", "ui_ux_ir": "ui_ux_ir:flogic"}[domain]
    space = features.build_feature_space(domain, [projection], train)
    adapter = fixtures.ui_targets if domain == "ui_ux_ir" else fixtures.domain_targets
    contract = features.build_native_feature_contract(space, ir_schema=domain + "/decoder-fixture-v1",
        adapter_sha256=hashlib.sha256(Path(adapter.__file__).read_bytes()).hexdigest())
    head = decoder.train_formal_decoder(space, train)
    trained = features.train_projection_features(contract, space, train, tune, epochs=16, learning_rate=0.02)
    inference = features.infer_projection_features(contract, space, trained["state"], train)
    decoded = decoder.decode_formal_features(space, head, inference)
    assert decoded["decoded_projection_count"] == 1, decoded
    assert trained["state"]["completed_epochs"] > 0
    zero = copy.deepcopy(trained["state"])
    zero["parameters"][2] = [[0.0 for value in row] for row in zero["parameters"][2]]
    zero["parameters"][3] = [0.0 for value in zero["parameters"][3]]
    assert decoder.decode_formal_features(space, head, features.infer_projection_features(contract, space, zero, train))["status"] == "abstained"


def test_native_v2_decode_preserves_original_latents_and_reconstructs_saved_head_math(monkeypatch):
    targets, tune = [fixtures._ui(1), fixtures._ui(2)], [fixtures._ui(3)]
    v1 = features.build_feature_space("ui_ux_ir", ["ui_ux_ir:flogic"], targets)
    digest = hashlib.sha256()
    for target in targets:
        streamed.update_target_digest(digest, target)
    space = streamed.build_streamed_feature_space(domain="ui_ux_ir", projection_ids=v1["projection_ids"],
        projections=v1["projections"], columns=v1["columns"], training_sources=v1["training_sources"],
        excluded_projection_ids=v1["excluded_projection_ids"], training_targets_sha256=digest.hexdigest())
    head = decoder.train_formal_decoder(space, iter(targets))
    train_matrix, train_ids, _ = features._matrix(space, targets)
    tune_matrix, tune_ids, _ = features._matrix(space, tune)
    trained = streamed.train_streamed_projection_features(space, train_matrix, train_ids, tune_matrix, tune_ids,
        minibatch_size=1, tuning_targets_sha256="b" * 64, epochs=16, latent_width=4, max_seconds=30)
    original = streamed.infer_streamed_projection_features(space, trained["state"], targets)
    result = decoder.infer_and_decode_native_v2(space, trained["state"], head, targets)
    assert result["model_inference"] == original
    assert result["decoded_projection_count"] == 2
    assert result["training_executed"] is False
    v2_path = Path(streamed.__file__).resolve()
    v2_key = "optimizers/logic_theorem_optimizer/autoencoder_projection_features_v2.py"
    assert head["validator_sources"][v2_key] == hashlib.sha256(v2_path.read_bytes()).hexdigest()
    original_read = Path.read_bytes
    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_bytes", lambda path: original_read(path) + b"\n# changed\n"
                      if path.resolve() == v2_path else original_read(path))
        with pytest.raises(decoder.FormulaDecoderError, match="sources changed"):
            decoder.validate_decoder(space, head)


def test_v2_head_fitting_streams_beyond_v1_batch_bound():
    import json
    raw = fixtures._ui(1).to_dict()
    v1 = features.build_feature_space("ui_ux_ir", ["ui_ux_ir:flogic"], [raw])
    def targets():
        # Authored envelope variants test the streaming boundary, not new
        # independently compiled examples or source-semantic generalization.
        for index in range(1025):
            target = json.loads(json.dumps(raw))
            target["source_digest"] = f"{index:064x}"
            yield target
    digest = hashlib.sha256()
    for target in targets():
        streamed.update_target_digest(digest, target)
    space = streamed.build_streamed_feature_space(domain="ui_ux_ir", projection_ids=v1["projection_ids"],
        projections=v1["projections"], columns=v1["columns"], training_sources=[f"{index:064x}" for index in range(1025)],
        excluded_projection_ids=v1["excluded_projection_ids"], training_targets_sha256=digest.hexdigest())
    head = decoder.train_formal_decoder(space, targets())
    assert head["training_source_count"] == 1025
    assert head["projections"]["ui_ux_ir:flogic"]["status"] == "ready"
