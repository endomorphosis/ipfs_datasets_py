"""Actual trained decoder outputs reach Lake; abstentions have no fallback."""
import copy
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_formula_learning as legal

PREFIX = "ipfs_datasets_py.optimizers.logic_theorem_optimizer"
ROOT = Path(features.__file__).resolve().parents[3]


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    parent, _, child = name.rpartition(".")
    if parent in sys.modules:
        setattr(sys.modules[parent], child, module)
    return module


staging = os.environ.get("DECODER_COMPLETION_STAGING")
if staging:
    stage = Path(staging)
    modules = stage / "ipfs_datasets_py/optimizers/logic_theorem_optimizer"
    for name in ("native_formula_training", "native_formula_checkpoint", "autoencoder_runtime_registry",
                 "autoencoder_schema_lake", "autoencoder_decoded_schema"):
        _load(modules / (name + ".py"), PREFIX + "." + name)
else:
    stage = ROOT
api = importlib.import_module(PREFIX + ".autoencoder_runtime_registry")
q = importlib.import_module(PREFIX + ".autoencoder_decoded_schema")
learning = importlib.import_module(PREFIX + ".native_formula_training")
fixtures = _load(stage / "tests/unit/optimizers/logic_theorem_optimizer/test_native_formula_training.py", "_decoded_schema_native_fixtures")
legal_fixtures = _load(ROOT / "tests/unit/optimizers/logic_theorem_optimizer/test_legal_formula_learning.py", "_decoded_schema_legal_fixtures")


@pytest.fixture(autouse=True)
def one_thread():
    import torch
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


@pytest.fixture(scope="module")
def legal_checkpoint():
    import torch
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    result = legal.train_decoder(legal_fixtures._examples(), [], epochs=100, **legal_fixtures.SETTINGS)
    torch.set_num_threads(previous)
    return result["checkpoint"]


def test_real_learned_legal_output_is_built_and_checkpoint_does_not_train(legal_checkpoint, tmp_path, monkeypatch):
    runtime = api.LearnedFormulaRuntime(checkpoint=legal_checkpoint)
    before = legal.checkpoint_digest(runtime.checkpoint)
    def forbidden(*args, **kwargs):
        raise AssertionError("schema validation must not train")
    monkeypatch.setattr(legal, "train_decoder", forbidden)
    sample = legal_fixtures._examples()[0]["source_text"]
    report = q.validate_decoded_outputs(runtime, [sample], output_directory=tmp_path / "legal")
    assert report["schema_checks_complete"] and report["schema_pass_count"] == 1
    assert report["input_count"] == report["schema_check_count"] == 1
    assert report["checkpoint_sha256"] == before == legal.checkpoint_digest(runtime.checkpoint)
    assert not report["training_executed"] and not report["admitted"] and not report["qualified"]
    retained = json.loads((tmp_path / "legal/inference.json").read_text())
    assert retained[0]["inference"]["rows"][0]["canonical_ir"] == legal_fixtures._examples()[0]["canonical_ir"]
    assert report["rows"][0]["source_binding_scope"] == "raw_source_text"


@pytest.mark.parametrize("domain", ("intent_ir", "security_ir", "ui_ux_ir"))
def test_actual_native_decoder_to_lake_keeps_structural_input_scope(domain, tmp_path):
    cp, train, tune = fixtures._build(domain)
    trained = learning.train_native_formula(cp, train, tune, epochs=35)
    runtime = api.NativeFormulaRuntime(domain, checkpoint=trained["checkpoint"])
    before = learning.checkpoint_digest(runtime.checkpoint)
    result = q.validate_decoded_outputs(runtime, train[:1], output_directory=tmp_path / domain)
    assert result["schema_checks_complete"] and result["schema_pass_count"] == 1, result
    row = result["rows"][0]
    assert row["source_binding_scope"] == "exact_model_input_artifact"
    assert row["native_input_source_digest"] == train[0]["source_digest"]
    assert row["exact_model_input_sha256"] != train[0]["source_digest"]
    assert result["checkpoint_sha256"] == before == learning.checkpoint_digest(runtime.checkpoint)
    assert all(result[key] is False for key in q.schema_lake.FALSE)
    inferred = json.loads((tmp_path / domain / "inference.json").read_text())[0]["inference"]
    assert inferred["decoder_kind"].startswith("learned_native_categorical")
    assert inferred["selected_weights"]


def test_zero_head_and_unknown_source_never_copy_input_or_compiler_output(legal_checkpoint, tmp_path, monkeypatch):
    import torch
    zero = copy.deepcopy(legal_checkpoint)
    for key in ("output.weight", "output.bias"):
        zero["model_state"][key] = torch.zeros_like(torch.tensor(zero["model_state"][key])).tolist()
    runtime = api.LearnedFormulaRuntime(checkpoint=zero)
    def forbidden(*args, **kwargs):
        raise AssertionError("abstention must not enter Lake")
    monkeypatch.setattr(q.schema_lake, "validate_schema_output", forbidden)
    samples = [legal_fixtures._examples()[0]["source_text"], "A spacecraft shall orbit Mars."]
    report = q.validate_decoded_outputs(runtime, samples, output_directory=tmp_path / "abstentions")
    assert report["input_count"] == 2 and report["schema_check_count"] == 0
    assert not report["schema_checks_complete"] and report["decoded_projection_count"] == 0
    assert all(row["outputs"][0]["status"] == "not_decoded" for row in report["rows"])
    retained = json.loads((tmp_path / "abstentions/inference.json").read_text())
    assert all(row["inference"]["rows"][0]["canonical_ir"] is None for row in retained)


def test_unsupported_runtime_wrong_domain_and_target_bearing_text_inputs_reject(tmp_path, legal_checkpoint):
    with pytest.raises(q.DecodedSchemaError, match="unsupported runtime"):
        q.validate_decoded_outputs(object(), ["text"], output_directory=tmp_path / "fake")
    runtime = api.LearnedFormulaRuntime(checkpoint=legal_checkpoint)
    with pytest.raises(q.DecodedSchemaError, match="only bounded source"):
        q.validate_decoded_outputs(runtime, legal_fixtures._examples(), output_directory=tmp_path / "target")
    cp, train, _ = fixtures._build("intent_ir")
    runtime = api.NativeFormulaRuntime("intent_ir", checkpoint=cp)
    _, wrong, _ = fixtures._build("security_ir")
    with pytest.raises(q.DecodedSchemaError, match="another domain"):
        q.validate_decoded_outputs(runtime, wrong[:1], output_directory=tmp_path / "wrong")
    assert not list(tmp_path.iterdir())


def test_inference_errors_are_retained_and_json_passed_claims_cannot_replace_execution(legal_checkpoint, tmp_path, monkeypatch):
    runtime = api.LearnedFormulaRuntime(checkpoint=legal_checkpoint)
    sample = legal_fixtures._examples()[0]["source_text"]
    with monkeypatch.context() as patch:
        def fail(*args, **kwargs):
            raise ValueError("authored decoder failure")
        patch.setattr(api.LearnedFormulaRuntime, "decode_formal_logic", fail)
        result = q.validate_decoded_outputs(runtime, [sample], output_directory=tmp_path / "failure")
    assert result["rows"][0]["status"] == "inference_error"
    assert "authored decoder failure" in result["rows"][0]["reason"]
    assert result["schema_check_count"] == 0 and not result["schema_checks_complete"]
    monkeypatch.setattr(q.schema_lake, "validate_schema_output", lambda *a, **k: {"schema_instance_typecheck_passed": True})
    result = q.validate_decoded_outputs(runtime, [sample], output_directory=tmp_path / "forged")
    assert result["rows"][0]["outputs"][0]["status"] == "schema_validation_error"
    assert result["schema_pass_count"] == 0 and not result["schema_checks_complete"]
