"""Real feature fitting and registry recovery for the explicit codebase profile.

These tiny authored targets exercise numerical plumbing, not held-out semantic
accuracy. Current-source/cohort admission belongs to the higher-level owner.
"""
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.logic.formalization.autoencoder import codebase_targets
from ipfs_datasets_py.logic.formalization.autoencoder.domain_targets import DomainTargetEnvelope
from ipfs_datasets_py.logic.software_contracts.codebase_integer_profile import IntegerOffsetContract
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as runtimes


def target(index, offset=1):
    name = f"increment_{index}"
    source = f"def {name}(n: int) -> int:\n    return n + {offset}\n".encode()
    return codebase_targets.prepare_codebase_targets(source,
        IntegerOffsetContract(f"unit_{index}.py", name, "n", offset), revision="snapshot:authored-codebase-fixture")


@pytest.fixture
def case():
    pytest.importorskip("torch")
    train, tune = [target(1, 1), target(2, 2)], [target(3, 1), target(4, 2)]
    runtime = runtimes.build_codebase_feature_runtime(train)
    return runtime, train, tune


def test_explicit_feature_runtime_does_not_advertise_other_objectives():
    assert "codebase_ir" not in runtimes.NATIVE_DOMAINS
    description = runtimes.describe_runtime("codebase_ir", "codebase_feature_v1")
    assert description["runtime_version"] == "codebase_feature_v1"
    assert description["dimension"] is None
    assert description["training_purpose"] == "feature_pretraining"
    assert description["formal_decoder"]["available"] is False
    assert "decode_formal_logic" not in description["capabilities"]
    assert all(description[key] is False for key in features.FALSE)
    assert "owner wrapper" in description["resource_policy"]


@pytest.mark.parametrize("version", ["native_v1", "native_v2", "native_formula_v1", "published_384_v1", "current_v2"])
def test_other_codebase_objectives_and_width_dispatch_are_rejected(version):
    with pytest.raises(runtimes.RuntimeVersionError, match="unknown codebase runtime"):
        runtimes.open_runtime("codebase_ir", version)


def test_target_dispatch_uses_exact_source_compiler():
    source = b"def plus(n: int) -> int:\n    return n + 1\n"
    contract = IntegerOffsetContract("plus.py", "plus", "n", 1)
    expected = codebase_targets.prepare_codebase_targets(source, contract, revision="snapshot:fixture")
    actual = runtimes.prepare_targets("codebase_ir", "codebase_feature_v1", source=source,
                                     contract=contract, revision="snapshot:fixture")
    assert actual == expected and actual.domain_id == "codebase_ir"


def test_train_register_reload_resumes_full_adam_and_preserves_basis(case, tmp_path):
    runtime, train, tune = case
    basis = runtime.feature_space
    assert runtime.describe()["latent_width"] == 8
    first = runtime.train(train, validation_samples=tune, epochs=1)
    assert first["report"]["improved"] and first["state"]["completed_epochs"] == 1
    assert all(row["step"] == 1 for row in first["state"]["adam"])
    import torch
    assert sum(torch.tensor(row["exp_avg"]).abs().sum().item() for row in first["state"]["adam"]) > 0
    expected = runtime.infer(tune)
    assert expected["training_executed"] is expected["decoded_formulas_generated"] is False
    assert expected["semantic_discrimination_guaranteed"] is False
    with AutoencoderRegistry(tmp_path / "models.duckdb", tmp_path / "artifacts", max_artifact_bytes=8 * 1024 * 1024) as registry:
        parent = runtime.register_candidate(registry, tmp_path / "parent")
        loaded = runtimes.load_version(registry, parent["version_id"], domain="codebase_ir", version="codebase_feature_v1")
        assert loaded.state == first["state"] and loaded.feature_space == basis
        assert loaded.infer(tune) == expected
        resumed = loaded.train(train, validation_samples=tune, epochs=1)
        uninterrupted = features.train_projection_features(runtime.contract, basis, train, tune, epochs=2, latent_width=8)
        assert resumed["state"] == uninterrupted["state"]
        assert resumed["report"]["base_state_sha256"] == features.digest(first["state"])
        child = loaded.register_candidate(registry, tmp_path / "child")
        assert registry.get_version(child["version_id"])["parent_version_id"] == parent["version_id"]
        assert registry.resolve_head(runtime.contract.variant_id, "main") is None
        assert runtime.feature_space == basis


def test_worker_result_registration_does_not_retrain_and_retains_cohort_metadata(case, tmp_path, monkeypatch):
    runtime, train, tune = case
    result = features.train_projection_features(runtime.contract, runtime.feature_space, train, tune, epochs=1, latent_width=8)
    # The current-source owner owns the schema and validation of this sidecar.
    result["report"]["codebase_cohort"] = {"schema": "authored-owner-sidecar@1", "role": "tuning_not_holdout"}
    def forbidden(*args, **kwargs):
        pytest.fail("worker result registration/load must not train")
    monkeypatch.setattr(features, "train_projection_features", forbidden)
    with AutoencoderRegistry(tmp_path / "models.duckdb", tmp_path / "artifacts") as registry:
        receipt = runtime.register_candidate_result(registry, tmp_path / "candidate", result)
        loaded = runtimes.load_version(registry, receipt["version_id"], domain="codebase_ir", version="codebase_feature_v1")
        assert loaded.training_report == result["report"]
        assert loaded.parent_version_id == receipt["version_id"]
        assert loaded.state == result["state"]
        loaded.training_report["codebase_cohort"]["role"] = "mutated"
        assert loaded.training_report["codebase_cohort"]["role"] == "tuning_not_holdout"


def test_registry_load_in_fresh_process_replays_exact_inference(case, tmp_path):
    runtime, train, tune = case
    runtime.train(train, validation_samples=tune, epochs=1)
    expected = runtime.infer(tune)
    database, artifacts = tmp_path / "models.duckdb", tmp_path / "artifacts"
    with AutoencoderRegistry(database, artifacts) as registry:
        receipt = runtime.register_candidate(registry, tmp_path / "candidate")
    samples = tmp_path / "samples.json"
    samples.write_text(json.dumps([value.to_dict() for value in tune]))
    script = '''
import json, sys
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_runtime_registry import load_version
def forbidden(*args, **kwargs):
    raise AssertionError("load/inference unexpectedly trained")
features.train_projection_features = forbidden
with AutoencoderRegistry(sys.argv[1], sys.argv[2]) as registry:
    runtime = load_version(registry, sys.argv[3], domain="codebase_ir", version="codebase_feature_v1")
    print(json.dumps(runtime.infer(json.load(open(sys.argv[4])))))
'''
    process = subprocess.run([sys.executable, "-c", script, str(database), str(artifacts), receipt["version_id"], str(samples)],
                             capture_output=True, text=True, timeout=45, env={**os.environ, "PYTHONPATH": os.getcwd()})
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout) == expected


def test_codebase_targets_are_revalidated_before_any_numerical_work(case, monkeypatch):
    runtime, train, tune = case
    changed = train[0].to_dict()
    changed["projections"][0]["expression"]["forged"] = True
    forged = DomainTargetEnvelope.from_dict(changed)
    def forbidden(*args, **kwargs):
        pytest.fail("forged native target reached numerical training")
    monkeypatch.setattr(features, "train_projection_features", forbidden)
    with pytest.raises(ValueError):
        runtime.train([forged], validation_samples=tune, epochs=1)
    with pytest.raises(ValueError):
        runtimes.build_codebase_feature_runtime([forged])


def test_new_cohort_uses_frozen_basis_and_unknown_literals_are_visible(case):
    runtime, train, tune = case
    basis = runtime.feature_space
    runtime.train(train, validation_samples=tune, epochs=1)
    unfamiliar = [target(5, 3), target(6, 4)]
    observed = runtime.infer(unfamiliar)
    assert observed["feature_coverage_complete"] is False
    assert all(row["unknown_atoms"] > 0 for row in observed["coverage"])
    # Dropped OOV atoms can collide; no semantic distinction is claimed.
    assert observed["rows"][0]["latent"] == observed["rows"][1]["latent"]
    assert observed["semantic_discrimination_guaranteed"] is False
    assert runtime.feature_space == basis


def test_changed_tuning_or_adapter_cannot_resume(case, tmp_path):
    runtime, train, tune = case
    runtime.train(train, validation_samples=tune, epochs=1)
    with AutoencoderRegistry(tmp_path / "models.duckdb", tmp_path / "artifacts") as registry:
        receipt = runtime.register_candidate(registry, tmp_path / "candidate")
        loaded = runtimes.load_version(registry, receipt["version_id"], domain="codebase_ir", version="codebase_feature_v1")
        with pytest.raises(features.ProjectionFeatureError, match="same tuning"):
            loaded.train(train, validation_samples=[target(99, 1)], epochs=1)
        assert loaded.state == runtime.state
    wrong = replace(runtime.contract, adapter=replace(runtime.contract.adapter, sha256="0" * 64))
    with pytest.raises(runtimes.RuntimeVersionError, match="adapter differs"):
        runtimes.open_runtime("codebase_ir", "codebase_feature_v1", contract=wrong, feature_space=runtime.feature_space)


def test_decoder_and_resume_overrides_fail_explicitly(case):
    runtime, train, tune = case
    with pytest.raises(runtimes.RuntimeVersionError, match="no formula decoder"):
        runtime.decode_formal_logic(train)
    with pytest.raises(runtimes.RuntimeVersionError, match="no formal decoder"):
        runtimes.open_formal_decoder("codebase_ir", "codebase_feature_v1")
    with pytest.raises(runtimes.RuntimeVersionError, match="resume state is bound"):
        runtime.train(train, validation_samples=tune, epochs=1, base_state={})


def test_wrong_worker_numerical_parent_cannot_publish(case, tmp_path):
    runtime, train, tune = case
    result = features.train_projection_features(runtime.contract, runtime.feature_space, train, tune, epochs=1, latent_width=8)
    result["report"]["base_state_sha256"] = "0" * 64
    with AutoencoderRegistry(tmp_path / "models.duckdb", tmp_path / "artifacts") as registry:
        with pytest.raises(runtimes.RuntimeVersionError, match="numerical parent"):
            runtime.register_candidate_result(registry, tmp_path / "candidate", result)
        assert not (tmp_path / "candidate").exists()


def test_parent_replaced_after_verification_is_read_with_byte_bound(case, tmp_path, monkeypatch):
    runtime, train, tune = case
    runtime.train(train, validation_samples=tune, epochs=1)
    with AutoencoderRegistry(tmp_path / "models.duckdb", tmp_path / "artifacts") as registry:
        parent = runtime.register_candidate(registry, tmp_path / "parent")
        runtime.train(train, validation_samples=tune, epochs=1)
        parent_path = registry.artifact_path(parent["artifact"])
        verify = registry.verify_artifact
        open_path = Path.open
        reads = []
        class ObservedReader:
            def __init__(self, stream):
                self.stream = stream
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.stream.close()
            def read(self, size=-1):
                reads.append(size)
                return self.stream.read(size)
        def observed_open(path, mode="r", *args, **kwargs):
            stream = open_path(path, mode, *args, **kwargs)
            return ObservedReader(stream) if path == parent_path and mode == "rb" else stream
        def replace_after_verify(artifact):
            result = verify(artifact)
            if artifact["sha256"] == parent["artifact"]["sha256"]:
                with open_path(parent_path, "r+b") as stream:
                    stream.truncate(64 * 1024 * 1024)
            return result
        monkeypatch.setattr(Path, "open", observed_open)
        monkeypatch.setattr(registry, "verify_artifact", replace_after_verify)
        with pytest.raises(features.ProjectionFeatureError, match="parent exceeds checkpoint bound"):
            runtime.register_candidate(registry, tmp_path / "child")
        assert reads[-1] == 32 * 1024 * 1024 + 1
        assert all(0 < size <= 32 * 1024 * 1024 + 1 for size in reads)
        assert not (tmp_path / "child").exists()
        assert runtime.parent_version_id == parent["version_id"]
