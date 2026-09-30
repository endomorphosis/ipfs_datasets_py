"""Public formula output and backward-compatible numeric checkpoints."""
import importlib
import importlib.util
import os
from pathlib import Path
import sys

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features

PREFIX = "ipfs_datasets_py.optimizers.logic_theorem_optimizer"
ROOT = Path(features.__file__).resolve().parents[3]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


stage = os.environ.get("IPFS_DATASETS_TEST_FORMAL_STAGING")
if stage:
    directory = Path(stage) / "ipfs_datasets_py/optimizers/logic_theorem_optimizer"
    for name in ("native_formal_decoder", "native_formal_checkpoint", "legal_formal_decoder", "autoencoder_runtime_registry"):
        _load(PREFIX + "." + name, directory / (name + ".py"))
runtime_api = importlib.import_module(PREFIX + ".autoencoder_runtime_registry")
decoder = importlib.import_module(PREFIX + ".native_formal_decoder")
fixture = _load("_formal_runtime_fixtures", ROOT / "tests/unit/optimizers/logic_theorem_optimizer/test_autoencoder_projection_features.py")
legal_fixture = _load("_formal_runtime_legal_fixtures", ROOT / "tests/unit/logic/test_autoencoder_lineage_runtimes.py")


@pytest.fixture(params=runtime_api.NATIVE_DOMAINS)
def native_case(request):
    producer = {"intent_ir": fixture._intent, "security_ir": fixture._security, "ui_ux_ir": fixture._ui}[request.param]
    train, tune = [producer(1), producer(2)], [producer(3), producer(4)]
    ids = [p["projection_id"] for p in train[0].to_dict()["projections"] if p["logic_family"]]
    return request.param, train, tune, ids


def test_decoder_head_persists_with_weights_and_resume(native_case, tmp_path):
    domain, train, tune, ids = native_case
    model = runtime_api.build_native_runtime(domain, "native_v1", train, projection_ids=ids,
        ir_schema=domain + "/fixture-v1")
    assert model.describe()["decoder_head_present"]
    assert model.describe()["variant_id"] != model.contract.variant_id
    head = model.decoder_head
    head["domain_id"] = "tampered"
    assert model.decoder_head["domain_id"] == domain
    model.train(train, validation_samples=tune, epochs=2)
    before = model.state
    decoded = model.decode_formal_logic(tune)
    assert model.state == before
    assert decoded["decoder_sha256"] == features.digest(model.decoder_head)
    assert decoded["training_executed"] is False and decoded["admitted"] is False
    assert all(p["expression"] is not None for row in decoded["rows"]
               for p in row["projections"] if p["status"] == "decoded_candidate")
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts") as registry:
        first = model.register_candidate(registry, tmp_path / "first")
        assert first["variant_id"] == model.describe()["variant_id"]
        loaded = runtime_api.load_version(registry, first["version_id"], domain=domain, version="native_v1")
        assert loaded.decoder_head == model.decoder_head
        assert loaded.decode_formal_logic(tune) == decoded
        loaded.train(train, validation_samples=tune, epochs=1)
        second = loaded.register_candidate(registry, tmp_path / "second")
        assert registry.get_version(second["version_id"])["parent_version_id"] == first["version_id"]


def test_old_numeric_checkpoint_is_readable_and_requires_explicit_head(native_case, tmp_path):
    domain, train, tune, ids = native_case
    model = runtime_api.build_native_runtime(domain, "native_v1", train, projection_ids=ids,
        ir_schema=domain + "/fixture-v1", with_formal_decoder=False)
    model.train(train, validation_samples=tune, epochs=1)
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts") as registry:
        first = model.register_candidate(registry, tmp_path / "numeric")
        assert first["variant_id"] == model.contract.variant_id
        loaded = runtime_api.load_version(registry, first["version_id"], domain=domain, version="native_v1")
        assert loaded.decode_formal_logic(tune)["status"] == "decoder_head_required"
        head = decoder.train_formal_decoder(loaded.feature_space, train)
        result = loaded.decode_formal_logic(tune, decoder_head=head)
        assert result["decoder_sha256"] == features.digest(head)
        assert loaded.decoder_head is None  # An explicit inference override does not migrate a checkpoint.
        assert loaded.infer(tune)["decoded_formulas_generated"] is False


@pytest.mark.parametrize("version", runtime_api.LEGAL_VERSIONS)
def test_every_legal_runtime_has_explicit_formal_output(version):
    lineage = importlib.import_module(PREFIX + ".autoencoder_lineages." + version)
    sample = legal_fixture.sample(lineage)
    runtime = runtime_api.open_formal_decoder("legal_ir", version, compute_device="cpu")
    before = runtime.model.state.to_dict()
    output = runtime.decode_formal_logic([sample], mode="canonical_compiler")
    assert output["formula_count"] > 0
    assert output["admitted"] is False
    assert runtime.model.state.to_dict() == before
    unavailable = runtime.decode_formal_logic([sample], mode="independent")
    assert unavailable["formula_count"] == 0
    assert unavailable["rows"][0]["status"] == "unsupported"
    assert "decode_formal_logic" in runtime.describe()["capabilities"]


def test_unknown_decoder_mode_is_not_silently_routed(native_case):
    domain, train, tune, ids = native_case
    model = runtime_api.build_native_runtime(domain, "native_v1", train, projection_ids=ids,
        ir_schema=domain + "/fixture-v1")
    with pytest.raises(runtime_api.RuntimeVersionError, match="mode"):
        model.decode_formal_logic(tune, mode="independent")


def test_head_source_drift_rejected_before_training(native_case, monkeypatch):
    domain, train, tune, ids = native_case
    model = runtime_api.build_native_runtime(domain, "native_v1", train, projection_ids=ids,
        ir_schema=domain + "/fixture-v1")
    def changed_source(*args, **kwargs):
        raise ValueError("decoder implementation source changed")
    monkeypatch.setattr(decoder, "validate_decoder", changed_source)
    with pytest.raises(ValueError, match="source changed"):
        model.train(train, validation_samples=tune, epochs=1)
    assert model.state is None


@pytest.mark.parametrize("version", runtime_api.LEGAL_VERSIONS)
def test_direct_lineage_facade_exposes_formal_output(version):
    if stage:
        pytest.skip("direct facade uses installed shared contract; validate after atomic install")
    lineage = importlib.import_module(PREFIX + ".autoencoder_lineages." + version)
    model = lineage.Autoencoder(compute_device="cpu")
    row = legal_fixture.sample(lineage)
    result = model.decode_formal_logic([row], mode="canonical_compiler")
    assert result["formula_count"] == 1
    assert result["rows"][0]["formal_outputs"][0]["payload"]["modality"] == "O"
    assert not result["admitted"]
    assert len(model.decode(model.encode(row, use_sample_memory=False))) == lineage.DIMENSION


def test_v2_descriptor_distinguishes_decoder_from_unimplemented_training_adapter():
    for domain in runtime_api.NATIVE_DOMAINS:
        item = runtime_api.describe_runtime(domain, "native_v2")
        assert item["formal_decoder"]["available"]
        assert item["formal_decoder"]["head_required"]
        assert not item["integrated"]
        with pytest.raises(runtime_api.RuntimeVersionError, match="not implemented"):
            runtime_api.open_runtime(domain, "native_v2")
