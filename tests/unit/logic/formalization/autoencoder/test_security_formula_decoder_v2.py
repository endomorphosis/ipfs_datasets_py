"""Expanded learned grammar, inherited weights, exact source checks and refusal."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from .test_security_formula_decoder import formula_checkpoint as parent_checkpoint
from ipfs_datasets_py.logic.formalization.autoencoder.security import security_formula_decoder as legacy
from ipfs_datasets_py.logic.formalization.autoencoder.security import security_formula_grammar as old_grammar
from ipfs_datasets_py.logic.formalization.autoencoder.security import security_formula_decoder_v2 as api
from ipfs_datasets_py.logic.formalization.autoencoder.security import security_formula_grammar_v2 as grammar
from ipfs_datasets_py.logic.formalization.autoencoder.security.security_formula_curriculum_v2 import authored_formula_samples_v2


@pytest.fixture(scope="module")
def expanded_checkpoint(parent_checkpoint, tmp_path_factory):
    parent_root = Path(parent_checkpoint["output"])
    original = {name: (parent_root / name).read_bytes() for name in legacy.FILES}
    descriptor = api.train_security_formula_decoder_v2(samples=authored_formula_samples_v2(),
        parent_checkpoint=parent_checkpoint, output=tmp_path_factory.mktemp("v2-expanded") / "security-decoder")
    assert original == {name: (parent_root / name).read_bytes() for name in legacy.FILES}
    return descriptor


def test_transferred_rows_are_exact_and_only_added_dimensions_start_at_zero(parent_checkpoint):
    parent = legacy.load_security_formula_decoder(parent_checkpoint)
    parameters, receipt = api.expand_parent_parameters(parent)
    before = parent["weights"]["parameters"]
    for i, feature in enumerate(old_grammar.FEATURES):
        assert parameters[0][grammar.FEATURES.index(feature)] == before[0][i]
    for i in range(parent["config"]["lexical_width"]):
        assert parameters[0][len(grammar.FEATURES) + i] == before[0][len(old_grammar.FEATURES) + i]
    for i, feature in enumerate(grammar.FEATURES):
        if feature not in old_grammar.FEATURES:
            assert parameters[0][i] == [0.] * parent["config"]["latent_width"]
    assert parameters[1] == before[1]
    for i, production in enumerate(old_grammar.PRODUCTIONS):
        j = grammar.PRODUCTIONS.index(production)
        assert [row[j] for row in parameters[2]] == [row[i] for row in before[2]]
        assert parameters[3][j] == before[3][i]
    assert receipt["parent_modified"] is False
    assert receipt["zero_added_production_columns"] == 9


def test_training_uses_actual_shared_loss_and_disjoint_structural_splits(expanded_checkpoint):
    loaded = api.load_security_formula_decoder_v2(expanded_checkpoint)
    receipt = loaded["training"]
    assert receipt["training_losses"][-1] < receipt["training_losses"][0]
    assert receipt["native_kernel_calls"] > 0 and max(receipt["gradient_norms"]) > 0
    assert receipt["initial_head_sha256"] != receipt["final_head_sha256"]
    assert receipt["metrics"]["train"]["exact_program_accuracy"] == 1.
    assert receipt["metrics"]["validation"]["exact_program_accuracy"] >= 5 / 6
    assert receipt["metrics"]["test"]["exact_program_accuracy"] >= 4 / 6
    assert receipt["heldout_used_for_fit"] is receipt["legal_parent_modified"] is False
    shapes = {split: {row["program_shape_sha256"] for row in rows} for split, rows in receipt["splits"].items()}
    assert not shapes["train"] & shapes["validation"]
    assert not shapes["train"] & shapes["test"]
    assert not shapes["validation"] & shapes["test"]
    raw = b"".join((Path(expanded_checkpoint["output"]) / name).read_bytes() for name in api.FILES)
    assert b"def " not in raw


@pytest.mark.parametrize("source", [
    b"def f(value):\n    return value <= 4\n",
    b"def f(value):\n    if value < 0:\n        return -value\n    return value\n",
    b"def f(value):\n    if value > 0:\n        result = value + 1\n        return result\n    else:\n        return 0\n",
    b"def f(value):\n    return True if value == 0 else False\n",
    b"def f(value):\n    return None if value != 0 else None\n",
    "def café(値):\n    return '安全' if 値 > 3 else '拒否'\n".encode(),
])
def test_expanded_predictions_are_learned_and_independently_replayed(expanded_checkpoint, source, monkeypatch):
    monkeypatch.setattr(api, "train_security_formula_decoder_v2", lambda **kw: pytest.fail("inference trained"))
    report = api.decode_security_formula_v2(source_bytes=source, checkpoint=expanded_checkpoint, source_path="control.py")
    assert report["status"] == "candidate", report["frontiers"]
    assert report["validation"]["source_AST_equivalent"]
    assert report["predicted_productions"] and report["neural_forward_count"] == 1
    assert report["learned_formula_count"] == 0  # Typed semantics are a separate projector.
    assert report["training_steps"] == report["provider_calls"] == report["solver_calls"] == 0
    assert report["proof_authority"] is report["whole_program_semantics_verified"] is False
    assert api.validate_security_formula_decode_v2(report, source_bytes=source, checkpoint=expanded_checkpoint) == report


@pytest.mark.parametrize("mode", ["model_off", "zero_heads"])
def test_disabled_or_zero_weights_cannot_receive_teacher_fallback(expanded_checkpoint, mode):
    report = api.decode_security_formula_v2(source_bytes=b"def f(value):\n    return value < 4\n",
        checkpoint=expanded_checkpoint, source_path="control.py", model_enabled=mode != "model_off",
        weight_ablation="zero_production_heads" if mode == "zero_heads" else None)
    assert report["status"] in {"unsupported", "rejected"}
    assert report["candidate"] is None and not report["validation"]["source_AST_equivalent"]
    assert report["neural_forward_count"] == (mode == "zero_heads")


def test_teacher_labels_never_enter_inference_predictions(expanded_checkpoint, monkeypatch):
    source = b"def f(value):\n    return value <= 7\n"
    parse = grammar.parse_formula_source
    def false_teachers(raw):
        value = parse(raw)
        for node in value["nodes"]:
            node["teacher_production"] = "deliberately_invalid_teacher"
        return value
    monkeypatch.setattr(grammar, "parse_formula_source", false_teachers)
    result = api.decode_security_formula_v2(source_bytes=source, checkpoint=expanded_checkpoint, source_path="control.py")
    assert result["status"] == "candidate" and result["validation"]["source_AST_equivalent"]


def test_utf8_spans_are_original_byte_spans():
    raw = "def café(値):\n    label = '安全'\n    return label if 値 != 3 else '拒否'\n".encode()
    observed = grammar.parse_formula_source(raw)
    for node in observed["nodes"]:
        span = raw[node["start_byte"]:node["end_byte"]]
        assert hashlib.sha256(span).hexdigest() == node["source_span_sha256"]
        span.decode("utf-8")
    literals = [node for node in observed["nodes"] if node["teacher_production"] == "string"]
    assert [raw[node["start_byte"]:node["end_byte"]].decode() for node in literals] == ["'安全'", "'拒否'"]
    assert next(node["shell"] for node in observed["nodes"] if node["teacher_production"] == "ne") == "!="
    grammar.compose_candidate(observed, [node["teacher_production"] for node in observed["nodes"]])


@pytest.mark.parametrize("source", [
    b"def f(value):\n    value = 1\n    return value\n",
    b"def f(value):\n    if value < 0:\n        local = 1\n        return local\n    return local\n",
    b"def f(value):\n    if value < 0:\n        local = 1\n    return value\n",
    b"def f(value):\n    return value / 0\n",
    b"def f(value):\n    return 0 < value < 8\n",
    b"def f(value):\n    return value\n    return 0\n",
    b"def f(value=effect()):\n    return value\n",
])
def test_unsupported_or_ambiguous_bindings_remain_explicit(source):
    with pytest.raises(grammar.UnsupportedFormulaSource):
        grammar.parse_formula_source(source)


def test_wrong_predicted_operator_is_rejected_instead_of_repaired():
    observed = grammar.parse_formula_source(b"def f(value):\n    return value <= 4\n")
    productions = [node["teacher_production"] for node in observed["nodes"]]
    productions[productions.index("le")] = "ge"
    with pytest.raises(ValueError, match="differs"):
        grammar.compose_candidate(observed, productions)


def test_cached_weights_and_replayed_report_tampering_are_rejected(expanded_checkpoint):
    source = b"def f(value):\n    return value < 4\n"
    loaded = deepcopy(api.load_security_formula_decoder_v2(expanded_checkpoint))
    loaded["weights"]["parameters"][3][0] += 50
    with pytest.raises(ValueError, match="cached decoder"):
        api.decode_security_formula_v2(source_bytes=source, checkpoint=expanded_checkpoint, source_path="control.py", loaded=loaded)
    report = api.decode_security_formula_v2(source_bytes=source, checkpoint=expanded_checkpoint, source_path="control.py")
    report["candidate_source"] = "def f(value):\n    return True\n"
    with pytest.raises(ValueError, match="replay differs"):
        api.validate_security_formula_decode_v2(report, source_bytes=source, checkpoint=expanded_checkpoint)


def test_training_refuses_cross_split_shape_before_output(parent_checkpoint, tmp_path):
    samples = authored_formula_samples_v2()
    samples.append({"id": "leaked", "split": "test", "source": "def renamed(other, third):\n    return other + 777\n"})
    output = tmp_path / "refused"
    with pytest.raises(ValueError, match="cross-split"):
        api.train_security_formula_decoder_v2(samples=samples, parent_checkpoint=parent_checkpoint, output=output)
    assert not output.exists()


@pytest.mark.parametrize("change", ["raw_body", "extra_tensor", "wrong_shape", "nonfinite", "wrong_transfer", "authority"])
def test_repinned_open_or_invalid_packages_remain_refused(expanded_checkpoint, tmp_path, change):
    import shutil
    destination = tmp_path / "tampered"
    shutil.copytree(expanded_checkpoint["output"], destination)
    descriptor = {**expanded_checkpoint, "output": str(destination)}
    if change == "authority":
        descriptor["proof_authority"] = 0
    else:
        filename = "training.json" if change in {"raw_body", "wrong_transfer"} else "weights.json"
        path = destination / filename
        value = json.loads(path.read_bytes())
        if change == "raw_body":
            value["source"] = "def forbidden(): pass"
        elif change == "extra_tensor":
            value["parameters"].append([1.])
        elif change == "wrong_shape":
            value["parameters"][0].pop()
        elif change == "wrong_transfer":
            value["parent_transfer"]["copied_feature_rows"] += 1
        else:
            value["parameters"][0][0][0] = float("nan")
        raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        path.chmod(0o644)
        path.write_bytes(raw)
        manifest_path = destination / "manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        manifest["files"][filename] = {"sha256": api._sha(raw), "bytes": len(raw)}
        raw = api._json(manifest)
        manifest_path.chmod(0o644)
        manifest_path.write_bytes(raw)
        descriptor = api._descriptor(destination, raw, manifest)
    with pytest.raises(ValueError):
        api.load_security_formula_decoder_v2(descriptor)


def test_feasibility_mask_uses_only_generic_binding_and_arity():
    row = {"binding": {"name": "lower"}, "children": [], "teacher_production": "lower",
        "shell": "some unrelated text", "features": [999.], "source_ast": "deliberately misleading"}
    assert grammar.feasible_productions(row) == ("name",)
    for value, expected in ((True, "boolean"), (1, "integer"), (None, "none"), ("lower", "string")):
        assert grammar.feasible_productions({"binding": {"value": value}, "children": []}) == (expected,)
    binary = {"binding": {}, "children": [0, 1]}
    alternatives = grammar.feasible_productions(binary)
    assert {"add", "sub", "mul", "eq", "ne", "lt", "le", "gt", "ge", "in", "not_in", "or", "and"} == set(alternatives)
    for expected in alternatives:
        assert grammar.feasible_productions({**binary, "teacher_production": expected, "shell": expected}) == alternatives


@pytest.mark.parametrize("name", ["lower", "upper", "title", "casefold", "replace", "str", "integer", "boolean", "value"])
def test_bound_identifiers_colliding_with_surface_or_method_names_decode(expanded_checkpoint, name):
    source = f"def identity({name}):\n    return {name} + 1\n".encode()
    report = api.decode_security_formula_v2(source_bytes=source, checkpoint=expanded_checkpoint, source_path="control.py")
    assert report["status"] == "candidate", report["frontiers"]
    observed = grammar.parse_formula_source(source)
    identifier_index = next(row["node_id"] for row in observed["nodes"] if row["binding"] == {"name": name})
    prediction = report["predicted_productions"][identifier_index]
    assert prediction["production"] == "name" and prediction["feasible_productions"] == ["name"]
    assert prediction["raw_production"] == grammar.PRODUCTIONS[max(range(len(prediction["logits"])), key=prediction["logits"].__getitem__)]
    assert prediction["constraint_changed_argmax"] == (prediction["raw_production"] != prediction["production"])


def test_mask_preserves_raw_neural_misclassification_and_logits(expanded_checkpoint):
    loaded = deepcopy(api.load_security_formula_decoder_v2(expanded_checkpoint))
    # Controlled actual tensor forward with a wrong raw method preference.
    loaded["weights"]["parameters"][2] = [[0.] * len(grammar.PRODUCTIONS) for _ in loaded["weights"]["parameters"][2]]
    loaded["weights"]["parameters"][3] = [0.] * len(grammar.PRODUCTIONS)
    loaded["weights"]["parameters"][3][grammar.PRODUCTIONS.index("lower")] = 9.
    observed = grammar.parse_formula_source(b"def identity(lower):\n    return lower\n")
    predictions = api._predictions(loaded, observed)
    first = predictions[0]
    assert first["raw_production"] == "lower" and first["production"] == "name"
    assert first["constraint_changed_argmax"] and first["logits"][grammar.PRODUCTIONS.index("lower")] == 9.
    assert first["raw_confidence"] > first["confidence"]
    assert first["constrained_confidence"] == 1.
