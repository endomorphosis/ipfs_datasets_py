"""One explicit interface; native compiler targets remain unqualified features."""
from dataclasses import replace
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest


def test_every_runtime_exposes_unfulfilled_lake_and_logic_requirements():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry
    descriptions = autoencoder_runtime_registry.list_runtimes()
    assert {row["domain"] for row in descriptions} == {"legal_ir", "intent_ir", "security_ir", "ui_ux_ir", "codebase_ir"}
    for row in descriptions:
        requirements = row["qualification_requirements"]
        assert requirements["domain"] == row["domain"]
        if row["domain"] == "codebase_ir" and row["runtime_version"] == "codebase_feature_v1":
            assert row["runtime_version"] not in {"native_v1", "native_v2", "native_formula_v1", "published_384_v1"}
            assert row["formal_decoder"]["available"] is False
            assert requirements["qualification_gaps"]
            assert requirements["qualified"] is requirements["admitted"] is False
            continue
        assert len(requirements["logic_floor"]) == 8
        assert requirements["lake_schema_requirement"]["required"]
        assert requirements["qualification_gaps"]
        assert requirements["qualified"] is requirements["admitted"] is False
        if row["domain"] in ("security_ir", "codebase_ir"):
            assert len(requirements["software_routes"]) == 14

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features


PREFIX = "ipfs_datasets_py.optimizers.logic_theorem_optimizer"
ROOT = Path(features.__file__).resolve().parents[3]


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


if os.environ.get("AUTOENCODER_RUNTIME_MODULE_PATH"):
    interface = _load(os.environ["AUTOENCODER_RUNTIME_MODULE_PATH"], PREFIX + ".autoencoder_runtime_registry")
else:
    interface = importlib.import_module(PREFIX + ".autoencoder_runtime_registry")

# Reuse the authored typed IR fixtures, including real native target compilers.
native_fixtures = _load(ROOT / "tests/unit/optimizers/logic_theorem_optimizer/test_autoencoder_projection_features.py",
                        "_runtime_native_fixtures")
legal_fixtures = _load(ROOT / "tests/unit/logic/test_autoencoder_lineage_runtimes.py", "_runtime_legal_fixtures")


@pytest.fixture(params=interface.NATIVE_DOMAINS)
def native_case(request):
    prepare = {"intent_ir": native_fixtures._intent, "security_ir": native_fixtures._security,
               "ui_ux_ir": native_fixtures._ui}[request.param]
    train, tune = [prepare(1), prepare(2)], [prepare(3), prepare(4)]
    ids = [row["projection_id"] for row in train[0].to_dict()["projections"] if row["logic_family"]]
    runtime = interface.build_native_runtime(request.param, "native_v1", train, projection_ids=ids,
        ir_schema=request.param + "/authored-fixture-v1", latent_width=4)
    return request.param, runtime, train, tune


def test_catalog_has_closed_versions_and_limited_source_identity():
    catalog = interface.list_runtimes()
    assert len({item["runtime_id"] for item in catalog}) == len(catalog)
    for domain in interface.NATIVE_DOMAINS:
        selected = {item["runtime_version"]: item for item in catalog if item["domain"] == domain}
        assert set(selected) == {"native_v1", "native_v2", "native_formula_v1", "published_384_v1"}
        assert selected["native_formula_v1"]["integrated"]
        assert selected["native_formula_v1"]["formal_decoder"]["trained_neural_decoder"]
        assert selected["native_v1"]["integrated"]
        assert not selected["native_v2"]["integrated"]
        assert selected["native_v2"]["capabilities"] == []
        with pytest.raises(interface.RuntimeVersionError, match="not implemented"):
            interface.open_runtime(domain, "native_v2")
    for item in catalog:
        assert all(item[key] is False for key in features.FALSE)
        assert item["source_identity"]["scope"] == "listed_runtime_files_only_not_transitive_dependency_provenance"
        assert len(item["source_identity"]["sha256"]) == 64
    with pytest.raises(interface.RuntimeVersionError, match="unknown"):
        interface.open_runtime("intent_ir", "../../arbitrary")
    with pytest.raises(interface.RuntimeVersionError, match="unknown"):
        interface.open_runtime("unknown_ir", "native_v1")


@pytest.mark.parametrize("domain", interface.NATIVE_DOMAINS)
def test_target_dispatch_preserves_actual_native_compiler_envelopes(domain, monkeypatch):
    fixture = {"intent_ir": native_fixtures._intent, "security_ir": native_fixtures._security,
               "ui_ux_ir": native_fixtures._ui}[domain]
    module, original = interface._target_adapter(domain)
    captured = {}
    def capture(*args, **kwargs):
        captured.update(kwargs)
        if args:
            assert len(args) == 1
            captured["document"] = args[0]
        return original(*args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(module, original.__name__, capture)
        expected = fixture(5)
    actual = interface.prepare_targets(domain, "native_v1", **captured)
    assert actual.to_dict() == expected.to_dict()
    assert actual.ready_for_training and not actual.to_dict()["admitted"]


def test_native_train_infer_registry_reload_and_exact_parent_resume(native_case, tmp_path):
    domain, runtime, train, tune = native_case
    with pytest.raises(interface.RuntimeVersionError, match="requires a trained"):
        runtime.infer(tune)
    first = runtime.train(train, validation_samples=tune, epochs=1)
    before = runtime.state
    with pytest.raises(interface.RuntimeVersionError, match="pending candidate"):
        runtime.train(train, validation_samples=tune, epochs=1)
    assert runtime.state == before
    expected = runtime.infer(tune)
    assert expected["training_executed"] is False
    assert not expected["decoded_formulas_generated"]
    assert first["report"]["training_target_count"] == 2
    assert set(first["report"]["after"]["projections"]) == {row.projection_id for row in runtime.contract.projections}
    database, artifacts = tmp_path / "control.duckdb", tmp_path / "artifacts"
    with AutoencoderRegistry(database, artifacts) as registry:
        parent = runtime.register_candidate(registry, tmp_path / "candidate-1")
    with AutoencoderRegistry(database, artifacts) as registry:
        loaded = interface.load_version(registry, parent["version_id"], domain=domain, version="native_v1")
        assert loaded.infer(tune) == expected
        assert loaded.state == runtime.state
        for foreign in set(interface.NATIVE_DOMAINS) - {domain}:
            with pytest.raises(interface.RuntimeVersionError, match="another domain"):
                interface.load_version(registry, parent["version_id"], domain=foreign, version="native_v1")
        resumed = loaded.train(train, validation_samples=tune, epochs=1)
        assert resumed["report"]["base_state_sha256"] == features.digest(first["state"])
        uninterrupted = features.train_projection_features(runtime.contract, runtime._space, train, tune, epochs=2)
        assert resumed["state"] == uninterrupted["state"]
        child = loaded.register_candidate(registry, tmp_path / "candidate-2")
        assert registry.get_version(child["version_id"])["parent_version_id"] == parent["version_id"]
        reloaded = interface.load_version(registry, child["version_id"], domain=domain, version="native_v1")
        assert reloaded.infer(tune) == loaded.infer(tune)
        assert reloaded.describe()["parent_version_id"] == child["version_id"]
        assert all(reloaded.describe()[key] is False for key in features.FALSE)


def test_incompatible_adapter_and_override_resume_are_rejected(native_case):
    domain, runtime, train, tune = native_case
    contract = replace(runtime.contract, adapter=replace(runtime.contract.adapter, sha256="0" * 64))
    with pytest.raises(interface.RuntimeVersionError, match="adapter differs"):
        interface.open_runtime(domain, "native_v1", contract=contract, feature_space=runtime._space)
    with pytest.raises(interface.RuntimeVersionError, match="resume state is bound"):
        runtime.train(train, validation_samples=tune, base_state={})
    with pytest.raises(interface.RuntimeVersionError, match="does not accept"):
        runtime.infer(tune, epochs=100)
    for changed in (replace(runtime.contract, optimizer=replace(runtime.contract.optimizer, version="2")),
                    replace(runtime.contract, adapter=replace(runtime.contract.adapter, version="2")),
                    replace(runtime.contract, adapter=replace(runtime.contract.adapter, identifier="other-adapter")),
                    replace(runtime.contract, state_codec=replace(runtime.contract.state_codec, version="bad"))):
        with pytest.raises(interface.RuntimeVersionError, match="version labels"):
            interface.open_runtime(domain, "native_v1", contract=changed, feature_space=runtime._space)


def test_registry_rejects_promoted_metadata_and_forged_parent(tmp_path, monkeypatch):
    train, tune = [native_fixtures._ui(1)], [native_fixtures._ui(2)]
    runtime = interface.build_native_runtime("ui_ux_ir", "native_v1", train,
        projection_ids=["ui_ux_ir:flogic"], ir_schema="ui_ux_ir/fixture-v1", with_formal_decoder=False)
    runtime.train(train, validation_samples=tune, epochs=1)
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts") as registry:
        registered = runtime.register_candidate(registry, tmp_path / "first")
        row = registry.get_version(registered["version_id"])
        with monkeypatch.context() as patch:
            patch.setattr(registry, "get_version", lambda _: {**row, "version_id": "0" * 64})
            with pytest.raises(interface.RuntimeVersionError, match="content identity differs"):
                interface.load_version(registry, row["version_id"], domain="ui_ux_ir", version="native_v1")
        fake = registry.register_version("forged-authority", row["variant_id"], row["artifact"],
            {**row["metadata"], "qualified": True})
        with pytest.raises(interface.RuntimeVersionError, match="metadata differs"):
            interface.load_version(registry, fake["version_id"], domain="ui_ux_ir", version="native_v1")
        fake_parent = registry.register_version("forged-parent", row["variant_id"], row["artifact"], row["metadata"],
                                               parent_version_id=row["version_id"])
        with pytest.raises(interface.RuntimeVersionError, match="numerical parent differs"):
            interface.load_version(registry, fake_parent["version_id"], domain="ui_ux_ir", version="native_v1")
        path = registry.artifact_path(row["artifact"])
        path.write_bytes(path.read_bytes() + b" ")
        with pytest.raises(ValueError, match="digest mismatch"):
            interface.load_version(registry, row["version_id"], domain="ui_ux_ir", version="native_v1")


@pytest.mark.parametrize("version", [entry["runtime_version"] for entry in interface.list_runtimes()
                                     if entry["domain"] == "legal_ir" and entry["runtime_version"] in interface.LEGAL_VERSIONS])
def test_legal_runtime_infers_trains_and_loads_explicit_checkpoint(version, tmp_path):
    lineage = importlib.import_module(PREFIX + ".autoencoder_lineages." + version)
    train, tune = legal_fixtures.sample(lineage), legal_fixtures.sample(lineage, "notices")
    runtime = interface.open_runtime("legal_ir", version, compute_device="cpu")
    metrics = runtime.infer([train], legal_ir_bridge_names=(), legal_ir_evaluate_provers=False, use_sample_memory=False)
    assert metrics.sample_count == 1 and metrics.legal_ir_target_count == 0
    assert len(metrics.decoded_embeddings[train.sample_id]) == lineage.DIMENSION
    options = {"projection_candidate_update_order": ("decoded_embedding",)} if version == "current_v2" else {}
    result = runtime.train([train], validation_samples=[tune], epochs=1, max_seconds=10,
        max_line_search_attempts=1, learning_rate=0.01, projection_max_update_families=1 if version == "current_v2" else 4,
        projection_update_backend="python_sparse_batch", legal_ir_bridge_names=(),
        legal_ir_evaluate_provers=False, **options)
    assert result["accepted_epochs"] == 1
    path = tmp_path / "state.json"
    runtime.model.state.save_json(path)
    expected_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    loaded = interface.open_runtime("legal_ir", version, checkpoint=path, expected_sha256=expected_sha, compute_device="cpu")
    assert loaded.model.state.to_dict() == runtime.model.state.to_dict()
    assert loaded.describe()["model"]["checkpoint_identity"]["sha256"] == expected_sha
    other = "legacy_v1" if version == "current_v2" else "current_v2"
    with pytest.raises(ValueError, match="expected .* values"):
        interface.open_runtime("legal_ir", other, compute_device="cpu").infer([train])
