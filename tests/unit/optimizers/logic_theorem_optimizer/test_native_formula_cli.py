"""CLI configuration and persistence tests; Lake itself is separately tested."""
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features

PREFIX = "ipfs_datasets_py.optimizers.logic_theorem_optimizer"
ROOT = Path(features.__file__).resolve().parents[3]
STAGE = Path(os.environ.get("DECODER_COMPLETION_STAGING", ROOT))


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    if name.startswith(PREFIX + "."):
        setattr(importlib.import_module(PREFIX), name.rsplit(".", 1)[1], module)
    return module


if os.environ.get("DECODER_COMPLETION_STAGING"):
    for name in ("native_formula_training", "native_formula_checkpoint", "autoencoder_runtime_registry",
                 "autoencoder_schema_lake", "autoencoder_decoded_schema"):
        _load(STAGE / "ipfs_datasets_py/optimizers/logic_theorem_optimizer" / (name + ".py"), PREFIX + "." + name)
learner = importlib.import_module(PREFIX + ".native_formula_training")
schema = importlib.import_module(PREFIX + ".autoencoder_decoded_schema")
cli = _load(STAGE / "scripts/ops/autoencoder/train_native_formula.py", "_native_formula_cli")
fixtures = _load(STAGE / "tests/unit/optimizers/logic_theorem_optimizer/test_native_formula_training.py", "_native_formula_cli_fixtures")


@pytest.fixture(autouse=True)
def one_thread(monkeypatch):
    import torch
    before = torch.get_num_threads()
    torch.set_num_threads(1)
    def schema_mock(runtime, samples, **options):
        # Exercise the actual learned readout; this stub grants no Lake result.
        inferred = runtime.infer(samples)
        return {"schema_checks_complete": True, "test_stub": True, "lake_executed": False,
                "decoded_projection_count": inferred["decoded_projection_count"], "admitted": False}
    monkeypatch.setattr(schema, "validate_decoded_outputs", schema_mock)
    yield
    torch.set_num_threads(before)


def _arguments(tmp_path, output="first"):
    corpus = tmp_path / "corpus.json"
    if not corpus.exists():
        train, tune, ids = fixtures._corpus("intent_ir")
        corpus.write_text(json.dumps({"training_targets": train, "tuning_targets": tune, "projection_ids": ids}))
    return ["--domain", "intent_ir", "--corpus", str(corpus), "--output", str(tmp_path / output),
            "--registry", str(tmp_path / "control.duckdb"), "--artifact-root", str(tmp_path / "artifacts"),
            "--epochs", "2", "--max-seconds", "30"]


def _last_json(capsys):
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def test_cli_fresh_and_resume_preserve_nondefault_optimizer(tmp_path, capsys):
    fresh = _arguments(tmp_path) + ["--latent-width", "8", "--learning-rate", ".04", "--batch-size", "1", "--seed", "42"]
    assert cli.main(fresh) == 0
    first = _last_json(capsys)
    cp = learner.load_checkpoint(first["checkpoint"]["path"], expected_sha256=first["checkpoint"]["sha256"])
    assert cp["config"]["learning_rate"] == .04 and cp["config"]["seed"] == 42
    assert cp["latest"]["progress"]["optimizer_steps"] == 4
    assert cli.main(_arguments(tmp_path, "second") + ["--parent-version", first["candidate"]["version_id"]]) == 0
    second = _last_json(capsys)
    resumed = learner.load_checkpoint(second["checkpoint"]["path"], expected_sha256=second["checkpoint"]["sha256"])
    assert resumed["config"] == cp["config"]
    assert resumed["latest"]["progress"]["optimizer_steps"] == 8
    assert resumed["parent_checkpoint_sha256"] == learner.checkpoint_digest(cp)


@pytest.mark.parametrize("option,value", [("--latent-width", "9"), ("--learning-rate", ".02"),
                                         ("--batch-size", "2"), ("--seed", "43")])
def test_explicit_conflicting_resume_options_reject_before_output(tmp_path, capsys, option, value):
    assert cli.main(_arguments(tmp_path) + ["--latent-width", "8", "--learning-rate", ".04", "--batch-size", "1", "--seed", "42"]) == 0
    first = _last_json(capsys)
    with pytest.raises(ValueError, match="immutable checkpoint"):
        cli.main(_arguments(tmp_path, "rejected") + ["--parent-version", first["candidate"]["version_id"], option, value])
    assert not (tmp_path / "rejected").exists()


def test_matching_resume_option_is_accepted_and_existing_output_preserved(tmp_path, capsys):
    args = _arguments(tmp_path) + ["--learning-rate", ".04"]
    assert cli.main(args) == 0
    first = _last_json(capsys)
    before = (tmp_path / "first/checkpoint.json").read_bytes()
    with pytest.raises(FileExistsError):
        cli.main(args)
    assert (tmp_path / "first/checkpoint.json").read_bytes() == before
    assert cli.main(_arguments(tmp_path, "second") + ["--parent-version", first["candidate"]["version_id"], "--learning-rate", ".04"]) == 0


def test_zero_deadline_returns_no_update_without_candidate(tmp_path, capsys):
    args = _arguments(tmp_path) + ["--max-seconds", "0"]
    assert cli.main(args) == 2
    result = _last_json(capsys)
    assert result["status"] == "no_optimizer_update"
    assert (tmp_path / "first/training.json").is_file()
    assert not (tmp_path / "first/checkpoint.json").exists()
    assert not (tmp_path / "first/registered").exists()


@pytest.mark.parametrize("raw", [
    '{"training_targets":[],"training_targets":[],"tuning_targets":[],"projection_ids":["x"]}',
    '{"training_targets":[NaN],"tuning_targets":[],"projection_ids":["x"]}',
    '{"training_targets":[],"tuning_targets":[],"projection_ids":["x","x"]}',
    '{"training_targets":[],"tuning_targets":[],"projection_ids":"x"}',
])
def test_bad_corpus_rejects_early(tmp_path, raw):
    path = tmp_path / "corpus.json"
    path.write_text(raw)
    with pytest.raises(ValueError):
        cli._read(path)


@pytest.mark.parametrize("count,ids", [(33, ["x"]), (0, ["x"]), (32, ["a", "b", "c", "d", "e"])])
def test_schema_capacity_rejects_before_training_or_registry_creation(tmp_path, count, ids):
    args = _arguments(tmp_path)
    path = tmp_path / "corpus.json"
    value = json.loads(path.read_text())
    value["tuning_targets"] = [value["tuning_targets"][0]] * count
    value["projection_ids"] = ids
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="CLI schema validation"):
        cli.main(args)
    assert not (tmp_path / "first").exists()
    assert not (tmp_path / "control.duckdb").exists()
