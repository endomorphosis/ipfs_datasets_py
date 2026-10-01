"""The legacy holdout runner cannot open targets before checkpoint validation."""
import json
from types import SimpleNamespace

import pytest

from scripts.ops.legal_ir import compare_legacy_prepared_training as module


def test_evaluation_requires_explicit_freeze_digest_before_loading_any_runtime(tmp_path, monkeypatch):
    (tmp_path / "frozen-fits.json").write_text("{}")
    monkeypatch.setattr(module, "runtimes", lambda: pytest.fail("runtime accessed before freeze verification"))
    with pytest.raises(RuntimeError, match="frozen-fit SHA-256"):
        module.evaluate(tmp_path, expected_freeze_sha256="0"*64)


def test_second_evaluation_refuses_before_loading_runtime_or_processing_sealed_targets(tmp_path, monkeypatch):
    path = tmp_path / "frozen-fits.json"
    path.write_text("{}")
    (tmp_path / "evaluation-started.json").write_text("{}")
    monkeypatch.setattr(module, "runtimes", lambda: pytest.fail("repeated evaluation accessed runtime"))
    with pytest.raises(RuntimeError, match="evaluation already started"):
        module.evaluate(tmp_path, expected_freeze_sha256=module.sha(path))


def test_all_model_bundles_validate_before_sealed_target_generation(tmp_path, monkeypatch):
    path = tmp_path / "frozen-fits.json"
    path.write_text("{}")
    (tmp_path / "development-inputs.json").write_text(json.dumps({"training": [], "tuning": []}))
    calls = []
    class Panel:
        def rows(self, split):
            calls.append(split)
            assert split != "sealed_evaluation", "sealed targets accessed before all bundles validated"
            return []
    initial = SimpleNamespace()
    profiles = SimpleNamespace(load_training_checkpoint=lambda *args, **kwargs: initial)
    def invalid(*args, **kwargs):
        raise ValueError("invalid saved runtime bundle")
    prepared = SimpleNamespace(load_training_session=invalid)
    monkeypatch.setattr(module, "runtimes", lambda: (None, None, prepared, profiles))
    monkeypatch.setattr(module.current, "panel", Panel)
    monkeypatch.setattr(module, "build", lambda model, rows: [])
    monkeypatch.setattr(module, "weights_digest", lambda model: "initial")
    monkeypatch.setattr(module, "frozen", lambda directory: dict(initial_weights_sha256="initial", results={
        arm: {"checkpoint": {"sha256": "0"*64}} for arm in module.ARMS}))
    with pytest.raises(ValueError, match="invalid saved runtime"):
        module.evaluate(tmp_path, expected_freeze_sha256=module.sha(path))
    assert calls == ["training", "tuning"]


def test_frozen_manifest_rejects_changed_files(tmp_path, monkeypatch):
    artifact = tmp_path / "model.json"
    artifact.write_text("initial")
    value = dict(source_hashes={}, results={arm: {} for arm in module.ARMS},
                 candidates_frozen_before_sealed_labels_or_predictions=True,
                 files={"model.json": module.sha(artifact)})
    (tmp_path / "frozen-fits.json").write_text(json.dumps(value))
    monkeypatch.setattr(module, "guard", lambda path: None)
    monkeypatch.setattr(module, "sources", dict)
    assert module.frozen(tmp_path) == value
    artifact.write_text("changed")
    with pytest.raises(RuntimeError, match="artifact changed"):
        module.frozen(tmp_path)


def test_fit_refuses_existing_directory_before_any_sample_build(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "runtimes", lambda: (None, None, None, None))
    monkeypatch.setattr(module, "sources", dict)
    monkeypatch.setattr(module.current, "panel", lambda: SimpleNamespace())
    monkeypatch.setattr(module, "build", lambda *args: pytest.fail("existing fit must not regenerate samples"))
    with pytest.raises(FileExistsError):
        module.fit(tmp_path)
