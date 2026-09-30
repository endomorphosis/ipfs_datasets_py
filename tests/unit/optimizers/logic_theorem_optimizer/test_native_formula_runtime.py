"""Decoder-aware native candidates retain exact numerical lineage in DuckDB."""
import copy
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features

PREFIX = "ipfs_datasets_py.optimizers.logic_theorem_optimizer"
ROOT = Path(features.__file__).resolve().parents[3]
STAGE = Path(os.environ.get("DECODER_COMPLETION_STAGING", ROOT))


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


if os.environ.get("DECODER_COMPLETION_STAGING"):
    for name in ("native_formula_training", "native_formula_checkpoint", "autoencoder_runtime_registry"):
        _load(STAGE / "ipfs_datasets_py/optimizers/logic_theorem_optimizer" / (name + ".py"), PREFIX + "." + name)
learning = importlib.import_module(PREFIX + ".native_formula_training")
storage = importlib.import_module(PREFIX + ".native_formula_checkpoint")
interface = importlib.import_module(PREFIX + ".autoencoder_runtime_registry")
fixture = _load(STAGE / "tests/unit/optimizers/logic_theorem_optimizer/test_native_formula_training.py", "_native_formula_registry_fixtures")


@pytest.fixture(autouse=True)
def one_thread():
    import torch
    before = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(before)


def _runtime(domain):
    train, tune, ids = fixture._corpus(domain)
    runtime = interface.build_native_formula_runtime(domain, train, validation_samples=tune,
        projection_ids=ids, latent_width=8, learning_rate=.04, batch_size=1)
    return runtime, train, tune


@pytest.mark.parametrize("domain", interface.NATIVE_DOMAINS)
def test_registry_reopen_resume_and_decode_use_same_numerical_weights(domain, tmp_path):
    runtime, train, tune = _runtime(domain)
    result = runtime.train(train, validation_samples=tune, epochs=2)
    with pytest.raises(interface.RuntimeVersionError, match="pending candidate"):
        runtime.train(train, validation_samples=tune, epochs=1)
    before = runtime.checkpoint
    decoded = runtime.infer(tune)
    assert runtime.checkpoint == before and not decoded["training_executed"]
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts") as registry:
        first = runtime.register_candidate(registry, tmp_path / "first")
        manifest = registry.get_variant(first["variant_id"])["manifest"]
        assert len(json.dumps(manifest).encode()) < 65536
        assert not first["admitted"] and not first["qualified"]
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts") as registry:
        restored = interface.load_version(registry, first["version_id"], domain=domain,
                                          version=interface.NATIVE_FORMULA_VERSION)
        assert restored.checkpoint == before and restored.infer(tune) == decoded
        resumed = restored.train(train, validation_samples=tune, epochs=1)
        direct = learning.train_native_formula(result["checkpoint"], train, tune, epochs=1)
        assert resumed["checkpoint"] == direct["checkpoint"]
        second = restored.register_candidate(registry, tmp_path / "second")
        assert registry.get_version(second["version_id"])["parent_version_id"] == first["version_id"]
        assert second["variant_id"] == first["variant_id"]
        assert storage.load_registered_candidate(registry, second["version_id"])["checkpoint"] == resumed["checkpoint"]
        foreign = "intent_ir" if domain != "intent_ir" else "security_ir"
        with pytest.raises(interface.RuntimeVersionError, match="another domain"):
            interface.load_version(registry, second["version_id"], domain=foreign,
                                   version=interface.NATIVE_FORMULA_VERSION)


def test_deadline_only_call_does_not_lock_runtime_behind_unregistrable_candidate():
    runtime, train, tune = _runtime("intent_ir")
    before = runtime.checkpoint
    result = runtime.train(train, validation_samples=tune, epochs=1, max_seconds=0)
    assert not result["report"]["training_executed"] and runtime.checkpoint == before
    result = runtime.train(train, validation_samples=tune, epochs=1)
    assert result["report"]["optimizer_steps"] == 2


def test_file_hash_defensive_copy_and_inference_mode(tmp_path):
    runtime, train, tune = _runtime("intent_ir")
    cp = runtime.checkpoint
    path = tmp_path / "initial.json"
    descriptor = learning.save_checkpoint(cp, path)
    restored = interface.open_formal_decoder("intent_ir", interface.NATIVE_FORMULA_VERSION,
        checkpoint=path, expected_sha256=descriptor["sha256"])
    assert restored.checkpoint == cp
    cp["latest"]["parameters"]["decoder_bias"][0] = 999
    assert restored.checkpoint != cp
    with pytest.raises(interface.RuntimeVersionError, match="only learned_fields"):
        restored.decode_formal_logic(train, mode="canonical_compiler")
    with pytest.raises(ValueError):
        interface.open_runtime("intent_ir", interface.NATIVE_FORMULA_VERSION,
            checkpoint=path, expected_sha256="a" * 64)


@pytest.mark.parametrize("field,value", [("qualified", True), ("proof_authority", True),
    ("source_semantics_verified", True), ("training_executed", False),
    ("checkpoint_sha256", "a" * 64), ("domain_id", "security_ir"),
    ("parent_checkpoint_sha256", "a" * 64), ("final_parameter_sha256", "a" * 64)])
def test_report_corruption_rejects_before_writing_candidate(field, value, tmp_path):
    runtime, train, tune = _runtime("intent_ir")
    result = runtime.train(train, validation_samples=tune, epochs=1)
    result["report"][field] = value
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts") as registry:
        with pytest.raises(ValueError):
            storage.register_candidate(registry, result, tmp_path / "bad")
        assert not (tmp_path / "bad").exists()


def test_false_authority_false_parent_and_artifact_tamper(tmp_path):
    runtime, train, tune = _runtime("intent_ir")
    runtime.train(train, validation_samples=tune, epochs=1)
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts") as registry:
        first = runtime.register_candidate(registry, tmp_path / "first")
        row = registry.get_version(first["version_id"])
        fake = registry.register_version("false-authority", row["variant_id"], row["artifact"],
            {**row["metadata"], "qualified": True})
        with pytest.raises(ValueError, match="metadata differs"):
            storage.load_registered_candidate(registry, fake["version_id"])
        fake = registry.register_version("false-parent", row["variant_id"], row["artifact"], row["metadata"],
            parent_version_id=row["version_id"])
        with pytest.raises(ValueError, match="numerical parent differs"):
            storage.load_registered_candidate(registry, fake["version_id"])
        artifact = registry.artifact_path(row["artifact"])
        artifact.write_bytes(artifact.read_bytes() + b" ")
        with pytest.raises(ValueError, match="digest mismatch"):
            storage.load_registered_candidate(registry, first["version_id"])
