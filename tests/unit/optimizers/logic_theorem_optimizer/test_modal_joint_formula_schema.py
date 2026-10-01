"""Actual trained 8D/384D heads reach Lake, without input/target substitution."""
from __future__ import annotations

import copy
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path

import pytest

PREFIX = "ipfs_datasets_py.optimizers.logic_theorem_optimizer"
api = importlib.import_module(PREFIX + ".autoencoder_runtime_registry")
q = importlib.import_module(PREFIX + ".autoencoder_decoded_schema")
modal = importlib.import_module(PREFIX + ".modal_joint_formula_schema")
learning = importlib.import_module(PREFIX + ".modal_latent_formula")
fixture_path = Path(__file__).with_name("test_modal_joint_formula.py")
spec = importlib.util.spec_from_file_location("_joint_formula_schema_fixtures", fixture_path)
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


@pytest.fixture(scope="module", params=("legacy_v1", "current_v2"))
def trained(request):
    import torch
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    version = request.param
    lineage = importlib.import_module(PREFIX + ".autoencoder_lineages." + version)
    runtime = api.LegalRuntime(version, compute_device="cpu")
    rows, tuning, targets, tuning_targets = fixtures._training_rows(lineage)
    result = runtime.train(rows, validation_samples=tuning,
        formula_targets=targets, validation_formula_targets=tuning_targets,
        formula_options={"learning_rate": 0.03, "batch_size": 2, "hidden_size": 16,
                         "token_embedding_dim": 8, "projection_width": 4, "seed": 1729},
        epochs=250, max_seconds=60)
    assert result["report"]["training_executed"]
    assert result["report"]["optimizer_steps"] == 250
    yield {"version": version, "checkpoint": result["checkpoint"], "rows": rows,
           "targets": targets, "lineage": lineage}
    torch.set_num_threads(previous)


def clone(trained):
    return api.LegalRuntime(trained["version"], compute_device="cpu",
                            formula_checkpoint=trained["checkpoint"])


def test_actual_joint_head_output_reaches_lake_with_separate_modal_and_source_bindings(trained, tmp_path, monkeypatch):
    runtime = clone(trained)
    before = learning.checkpoint_digest(runtime.model.formula_checkpoint)
    core_before = modal.joint._core_binding(runtime.model)
    sample = trained["rows"][0]
    def forbidden(*args, **kwargs):
        raise AssertionError("schema observation cannot train or substitute a compiler")
    monkeypatch.setattr(modal.joint, "train", forbidden)
    compiler = importlib.import_module(PREFIX + ".legal_formal_decoder")
    monkeypatch.setattr(compiler, "decode_legal_formulas", forbidden)
    report = q.validate_decoded_outputs(runtime, [sample], output_directory=tmp_path / "actual")
    assert report["schema_checks_complete"], report
    assert report["lake_build_count"] == report["schema_pass_count"] == 1
    assert report["dimension"] == trained["lineage"].DIMENSION
    assert report["checkpoint_sha256"] == before == learning.checkpoint_digest(runtime.model.formula_checkpoint)
    assert report["core_binding"] == core_before == modal.joint._core_binding(runtime.model)
    assert report["runtime_binding_unchanged"]
    assert report["parser_features_in_input"] and not report["independent_text_to_logic"]
    assert report["supported_logic_families"] == ["deontic"]
    assert all(report[key] is False for key in modal.schema_lake.FALSE)
    assert not report["training_executed"]
    inputs = json.loads((tmp_path / "actual/inputs.json").read_text())
    sources = json.loads((tmp_path / "actual/sources.json").read_text())
    inferred = json.loads((tmp_path / "actual/inference.json").read_text())[0]["inference"]
    assert inputs == [sample.to_dict()]
    assert sources[0]["source_text"] == sample.text
    assert sources[0]["source_sha256"] == hashlib.sha256(sample.text.encode()).hexdigest()
    assert report["rows"][0]["exact_model_input_sha256"] != sources[0]["source_sha256"]
    assert inferred["rows"][0]["canonical_ir"] == trained["targets"][0]["canonical_ir"]
    assert inferred["checkpoint_sha256"] == before
    assert inferred["rows"][0]["target_access"] is False
    command = report["rows"][0]["outputs"][0]["lake_receipt"]["command"]
    assert Path(command[0]).name == "lake" and command[1:] == ["build", "DecoderSchema"]


@pytest.mark.parametrize("field", ("source_sha256", "latent_sha256", "id"))
def test_changed_inference_capture_cannot_reach_lake(trained, tmp_path, monkeypatch, field):
    runtime = clone(trained)
    original = api.LegalRuntime.infer
    def changed(self, samples):
        result = original(self, samples)
        result["rows"][0][field] = "incorrect-captured-binding"
        return result
    monkeypatch.setattr(api.LegalRuntime, "infer", changed)
    monkeypatch.setattr(modal.schema_lake, "validate_schema_output", lambda *a, **k: pytest.fail("changed capture reached Lake"))
    report = q.validate_decoded_outputs(runtime, trained["rows"][:1], output_directory=tmp_path / field)
    assert not report["schema_checks_complete"] and report["lake_build_count"] == 0
    assert report["rows"][0]["status"] == "inference_error"
    assert all(report[key] is False for key in modal.schema_lake.FALSE)


@pytest.mark.parametrize("change", ("core", "input"))
def test_mutation_during_capture_fails_closed(trained, tmp_path, monkeypatch, change):
    runtime = clone(trained)
    samples = copy.deepcopy(trained["rows"][:1])
    original = api.LegalRuntime.infer
    def changed(self, rows):
        result = original(self, rows)
        if change == "core":
            self.model.state.family_embedding_weights["deontic"] = [0.1] * self.model.DIMENSION
        else:
            rows[0].losses["mutated_during_capture"] = 1.
        return result
    monkeypatch.setattr(api.LegalRuntime, "infer", changed)
    report = q.validate_decoded_outputs(runtime, samples, output_directory=tmp_path / change)
    assert report["runtime_binding_unchanged"] is False
    assert report["schema_checks_complete"] is False and report["lake_build_count"] == 0
    assert report["rows"][0]["status"] == "inference_error"


def test_wrong_core_or_cached_decoder_weights_reject_before_capture(trained, tmp_path):
    import torch
    runtime = clone(trained)
    runtime.model.initial_embedding_scale += .01
    with pytest.raises(ValueError, match="core differ"):
        q.validate_decoded_outputs(runtime, trained["rows"][:1], output_directory=tmp_path / "core")
    runtime = clone(trained)
    with torch.no_grad():
        runtime.model._joint_formula_decoder.model.output.bias[0] += .1
    with pytest.raises(ValueError, match="cached decoder weights differ"):
        q.validate_decoded_outputs(runtime, trained["rows"][:1], output_directory=tmp_path / "head")
    assert not list(tmp_path.iterdir())


def test_zero_head_abstains_without_compiler_or_target_fallback(trained, tmp_path, monkeypatch):
    import torch
    checkpoint = copy.deepcopy(trained["checkpoint"])
    for key in ("output.weight", "output.bias"):
        checkpoint["model_state"][key] = torch.zeros_like(torch.tensor(checkpoint["model_state"][key])).tolist()
    runtime = api.LegalRuntime(trained["version"], compute_device="cpu", formula_checkpoint=checkpoint)
    monkeypatch.setattr(modal.schema_lake, "validate_schema_output", lambda *a, **k: pytest.fail("abstention reached Lake"))
    report = q.validate_decoded_outputs(runtime, trained["rows"][:1], output_directory=tmp_path / "abstained")
    assert not report["schema_checks_complete"]
    assert report["schema_check_count"] == report["decoded_projection_count"] == 0
    assert report["rows"][0]["outputs"][0]["decoder_status"] == "abstained"
    assert report["rows"][0]["outputs"][0]["reason"] == "zero_output_head"
    retained = json.loads((tmp_path / "abstained/inference.json").read_text())
    assert retained[0]["inference"]["rows"][0]["canonical_ir"] is None


def test_json_success_cannot_replace_real_lake_execution(trained, tmp_path, monkeypatch):
    runtime = clone(trained)
    monkeypatch.setattr(modal.schema_lake, "validate_schema_output", lambda *a, **k: {"schema_instance_typecheck_passed": True})
    report = q.validate_decoded_outputs(runtime, trained["rows"][:1], output_directory=tmp_path / "forged")
    assert not report["schema_checks_complete"] and report["schema_pass_count"] == 0
    assert report["rows"][0]["outputs"][0]["status"] == "schema_validation_error"


def test_wrong_lineage_sample_and_instance_decoder_rejected(trained, tmp_path):
    runtime = clone(trained)
    other = "current_v2" if trained["version"] == "legacy_v1" else "legacy_v1"
    other_lineage = importlib.import_module(PREFIX + ".autoencoder_lineages." + other)
    wrong = fixtures.sample(other_lineage)
    with pytest.raises(ValueError, match="exact typed samples"):
        q.validate_decoded_outputs(runtime, [wrong], output_directory=tmp_path / "wrong")
    runtime.infer = lambda samples: {"status": "success"}
    with pytest.raises(ValueError, match="instance method replacements"):
        q.validate_decoded_outputs(runtime, trained["rows"][:1], output_directory=tmp_path / "instance")
    assert not list(tmp_path.iterdir())
