"""Public source-only formula inference and exact owner-controlled versions."""
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
stage = os.environ.get("LEARNED_FORMULA_STAGING")
if stage:
    directory = Path(stage) / "ipfs_datasets_py/optimizers/logic_theorem_optimizer"
    for name in ("legal_formula_codec", "legal_formula_learning", "legal_formula_checkpoint", "autoencoder_runtime_registry"):
        spec = importlib.util.spec_from_file_location(PREFIX + "." + name, directory / (name + ".py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
learning = importlib.import_module(PREFIX + ".legal_formula_learning")
interface = importlib.import_module(PREFIX + ".autoencoder_runtime_registry")


@pytest.fixture(scope="module")
def corpus():
    fixture_root = Path(stage) if stage else ROOT
    return json.loads((fixture_root / "tests/fixtures/legal_formula_learning/v1.json").read_text())


@pytest.fixture(scope="module")
def trained(corpus):
    import torch
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        yield learning.train_decoder(corpus["train"], corpus["tuning"], epochs=1, max_seconds=30)
    finally:
        torch.set_num_threads(previous)


def test_new_model_is_explicit_and_does_not_relabel_legacy_profiles():
    item = interface.describe_runtime("legal_ir", interface.LEARNED_FORMULA_VERSION)
    assert item["input_representation"] == "source_text"
    assert item["formal_decoder"]["independent_learned_formula_decoder"]
    for version in interface.LEGAL_VERSIONS:
        old = interface.describe_runtime("legal_ir", version)
        assert not old["formal_decoder"]["independent_learned_formula_decoder"]
        assert old["dimension"] == (384 if version == "current_v2" else 8)
    runtime = interface.open_runtime("legal_ir", interface.LEARNED_FORMULA_VERSION)
    with pytest.raises(interface.RuntimeVersionError, match="train or load"):
        runtime.infer(["The agency shall submit records."])


def test_file_checkpoint_load_and_source_only_inference_are_read_only(trained, corpus, tmp_path):
    path = tmp_path / "checkpoint.json"
    saved = learning.save_checkpoint(trained["checkpoint"], path)
    runtime = interface.open_formal_decoder("legal_ir", interface.LEARNED_FORMULA_VERSION,
        checkpoint=path, expected_sha256=saved["sha256"])
    before = runtime.checkpoint
    source = [row["source_text"] for row in corpus["heldout"][:2]]
    result = runtime.decode_formal_logic(source)
    assert result == runtime.infer(source)
    assert runtime.checkpoint == before
    before["lineage_id"] = "tampered"
    assert runtime.checkpoint["lineage_id"] == interface.LEARNED_FORMULA_VERSION
    with pytest.raises(interface.RuntimeVersionError, match="only learned"):
        runtime.decode_formal_logic(source, mode="canonical_compiler")
    with pytest.raises(ValueError):
        runtime.decode_formal_logic(corpus["heldout"][:2])  # Target-bearing examples are not inference inputs.


def test_duckdb_reload_and_parent_linked_training(corpus, tmp_path):
    import torch
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        runtime = interface.open_runtime("legal_ir", interface.LEARNED_FORMULA_VERSION)
        result = runtime.train(corpus["train"], validation_samples=corpus["tuning"], epochs=1, max_seconds=30)
        with pytest.raises(interface.RuntimeVersionError, match="pending candidate"):
            runtime.train(corpus["train"], validation_samples=corpus["tuning"], epochs=1)
        with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts") as registry:
            first = runtime.register_candidate(registry, tmp_path / "first")
            assert not first["admitted"] and not first["qualified"]
        with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts") as registry:
            restored = interface.load_version(registry, first["version_id"], domain="legal_ir",
                                             version=interface.LEARNED_FORMULA_VERSION)
            assert restored.checkpoint == result["checkpoint"]
            source = [corpus["heldout"][0]["source_text"]]
            assert restored.infer(source) == runtime.infer(source)
            resumed = restored.train(corpus["train"], validation_samples=corpus["tuning"], epochs=1, max_seconds=30)
            assert resumed["checkpoint"]["progress"]["optimizer_steps"] > result["checkpoint"]["progress"]["optimizer_steps"]
            second = restored.register_candidate(registry, tmp_path / "second")
            assert registry.get_version(second["version_id"])["parent_version_id"] == first["version_id"]
            loaded = interface.load_version(registry, second["version_id"], domain="legal_ir",
                                           version=interface.LEARNED_FORMULA_VERSION)
            assert loaded.checkpoint == resumed["checkpoint"]
    finally:
        torch.set_num_threads(previous)


def test_registry_rejects_authority_and_false_parent(trained, tmp_path):
    storage = importlib.import_module(PREFIX + ".legal_formula_checkpoint")
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts") as registry:
        first = storage.register_candidate(registry, trained, tmp_path / "first")
        row = registry.get_version(first["version_id"])
        fake = registry.register_version("false-authority", row["variant_id"], row["artifact"],
                                        {**row["metadata"], "qualified": True})
        with pytest.raises(ValueError, match="metadata differs"):
            storage.load_registered_candidate(registry, fake["version_id"])
        fake = registry.register_version("false-parent", row["variant_id"], row["artifact"], row["metadata"],
                                        parent_version_id=row["version_id"])
        with pytest.raises(ValueError, match="numerical parent differs"):
            storage.load_registered_candidate(registry, fake["version_id"])
        path = registry.artifact_path(row["artifact"])
        path.write_bytes(path.read_bytes() + b" ")
        with pytest.raises(ValueError, match="digest mismatch"):
            storage.load_registered_candidate(registry, row["version_id"])


@pytest.mark.parametrize("field,value", [("proof_authority", True), ("semantic_correctness_verified", True),
    ("publication_performed", True), ("checkpoint_sha256", "a" * 64),
    ("final_model_state_sha256", "b" * 64), ("final_output_head_sha256", "c" * 64),
    ("progress", {"optimizer_steps": 999}), ("schema", "foreign"), ("lineage_id", "legacy_hub_v1")])
def test_forged_training_report_rejected_before_registration(trained, tmp_path, field, value):
    storage = importlib.import_module(PREFIX + ".legal_formula_checkpoint")
    forged = copy.deepcopy(trained)
    forged["report"][field] = value
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts") as registry:
        with pytest.raises(ValueError):
            storage.register_candidate(registry, forged, tmp_path / "candidate")
        assert not (tmp_path / "candidate").exists()
