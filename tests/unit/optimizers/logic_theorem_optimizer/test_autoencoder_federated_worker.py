"""Pinned local data and genuine Legal trainer coverage for federated workers."""

import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_federated_worker as worker
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_federated import ClientSpec


PRODUCER = "b" * 64


def payload(dimension=8):
    def row(section, text):
        return {
            "title": "5", "section": str(section), "text": text,
            "embedding_model": "fixture:explicit-local-vectors",
            "embedding_vector": [0.1] * dimension,
        }
    return {
        "schema": worker.CLIENT_DATA_SCHEMA, "embedding_producer_sha256": PRODUCER,
        "training": [row(1, "The agency must provide notice.")],
        "validation": [row(2, "The agency must publish notice.")],
    }


def write_payload(path, value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture(scope="module", params=("legacy_v1", "current_v2"))
def prepared(request, tmp_path_factory):
    """Author small verified bases with every local semantic row predeclared.

    The existing trainer creates sparse keys. The owner must establish their
    union before a fixed-layout round; this test's authored base uses actual
    sparse training operators to enumerate that union without fitting a head.
    """
    from importlib import import_module
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_federated_modal import load_modal_checkpoint

    version = request.param
    namespace = import_module(
        "ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages." + version,
    )
    data = payload(namespace.DIMENSION)
    model = namespace.Autoencoder(compute_device="python")
    rows = [namespace.build_sample(**row) for row in data["training"] + data["validation"]]
    model.evaluate(rows, legal_ir_bridge_names=(), legal_ir_evaluate_provers=False,
                   use_sample_memory=False)
    options = {"raw_decoder_objective": True} if version == "current_v2" else {}
    model._apply_projection_update_batch(
        rows, update_targets=("decoded_embedding", "family_logits"),
        learning_rate=.001, l2_regularization=0, update_backend="python_sparse_batch", **options,
    )
    directory = tmp_path_factory.mktemp("federated-worker-" + version)
    base_path = directory / "base.json"
    model.state.save_json(base_path)
    adapter = load_modal_checkpoint(
        base_path, expected_sha256=hashlib.sha256(base_path.read_bytes()).hexdigest(),
        runtime_version=version,
    )
    return adapter, data, directory


def round_for(adapter, path, data, *, sample_count=None):
    digest = write_payload(path, data)
    client = ClientSpec("worker-a", len(data["training"]) if sample_count is None else sample_count, digest)
    round_spec = adapter.make_round(
        round_id="local-round", model_id="shared-legal-model", clients=(client,),
        embedding_producer_sha256=PRODUCER, max_local_steps=3,
    )
    return round_spec


@pytest.fixture(scope="module", params=("legacy_v1", "current_v2"))
def boundary_base(request, tmp_path_factory):
    """A tiny genuine verified base suffices for failures before training."""
    from importlib import import_module
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_federated_modal import load_modal_checkpoint

    namespace = import_module(
        "ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages." + request.param,
    )
    directory = tmp_path_factory.mktemp("worker-boundary-" + request.param)
    base_path = directory / "base.json"
    namespace.TrainingState(feature_embedding_weights={
        "owner-declared-feature": [0.1] * namespace.DIMENSION,
    }).save_json(base_path)
    adapter = load_modal_checkpoint(
        base_path, expected_sha256=hashlib.sha256(base_path.read_bytes()).hexdigest(),
        runtime_version=request.param,
    )
    return adapter, payload(namespace.DIMENSION), directory


def test_genuine_local_training_for_each_legal_lineage(prepared, tmp_path):
    adapter, data, _ = prepared
    path = tmp_path / "data.json"
    round_spec = round_for(adapter, path, data)
    update, report = worker.train_modal_client(
        adapter, round_spec, "worker-a", path, compute_device="python", max_seconds=30,
    )
    assert update.local_data_sha256 == round_spec.clients[0].local_data_sha256
    assert update.round_sha256 == round_spec.round_sha256
    assert update.local_steps == report["attempted_epochs"] == 1
    assert report["requested_epochs"] == 1
    assert report["dimension"] == round_spec.dimension
    assert report["optimizer_reset"] and report["sample_memory_used"] is False
    assert report["tuning_used_for_selection"] and not report["independent_validation"]
    assert report["qualified"] is report["publication_performed"] is False
    assert report["training_scope"] == "reusable_modal_feature_heads"
    assert report["formula_training_executed"] is False
    assert hashlib.sha256(Path(adapter.path).read_bytes()).hexdigest() == adapter.base_sha256
    assert len(json.dumps(report)) < 4096
    if adapter.runtime_version == "current_v2":
        assert report["reconstruction_objective"] == "raw_decoder"
        assert report["accepted_epochs"] == 1
        assert any(coordinates for coordinates in update.deltas.values())
        assert report["tuning_metrics_after"]["reconstruction_loss"] < report["tuning_metrics_before"]["reconstruction_loss"]
    else:
        assert report["reconstruction_objective"] == "historical_safety_projected"
        assert report["accepted_epochs"] == 0  # Honest historical fixture outcome.


@pytest.mark.parametrize("change", [
    "producer", "dimension", "bool_vector", "infinite_vector", "unknown_row",
    "missing_embedding_model", "empty_validation", "overlap_text", "overlap_id", "count",
])
def test_invalid_approved_dataset_is_rejected_before_model_creation(boundary_base, tmp_path, monkeypatch, change):
    adapter, original, _ = boundary_base
    data = json.loads(json.dumps(original))
    sample_count = None
    if change == "producer":
        data["embedding_producer_sha256"] = "c" * 64
    elif change == "dimension":
        data["training"][0]["embedding_vector"].pop()
    elif change == "bool_vector":
        data["training"][0]["embedding_vector"][0] = True
    elif change == "infinite_vector":
        data["training"][0]["embedding_vector"][0] = float("inf")
    elif change == "unknown_row":
        data["training"][0]["optimizer"] = {}
    elif change == "missing_embedding_model":
        del data["training"][0]["embedding_model"]
    elif change == "empty_validation":
        data["validation"] = []
    elif change == "overlap_text":
        data["validation"][0]["text"] = "  THE AGENCY MUST PROVIDE NOTICE. "
    elif change == "overlap_id":
        data["validation"] = json.loads(json.dumps(data["training"]))
    else:
        sample_count = 2
    path = tmp_path / "invalid.json"
    round_spec = round_for(adapter, path, data, sample_count=sample_count)
    def forbidden_model(*_args, **_kwargs):
        pytest.fail("invalid data reached private model creation")
    monkeypatch.setattr(type(adapter), "fresh_model", forbidden_model)
    with pytest.raises(ValueError):
        worker.train_modal_client(adapter, round_spec, "worker-a", path, compute_device="python")


def test_modified_file_and_unknown_client_rejected(boundary_base, tmp_path):
    adapter, data, _ = boundary_base
    path = tmp_path / "data.json"
    round_spec = round_for(adapter, path, data)
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(worker.FederatedWorkerError, match="SHA-256"):
        worker.train_modal_client(adapter, round_spec, "worker-a", path)
    with pytest.raises(worker.FederatedWorkerError, match="not approved"):
        worker.train_modal_client(adapter, round_spec, "unknown", path)


@pytest.mark.parametrize("options", [
    {"epochs": True}, {"epochs": 4}, {"learning_rate": float("nan")},
    {"learning_rate": 10 ** 1000}, {"max_seconds": -1},
    {"max_line_search_attempts": 0}, {"compute_device": "auto"}, {"compute_device": "cuda"},
])
def test_worker_bounds_checked_before_data_read(boundary_base, tmp_path, options):
    adapter, data, _ = boundary_base
    path = tmp_path / "data.json"
    round_spec = round_for(adapter, path, data)
    path.unlink()
    with pytest.raises(worker.FederatedWorkerError):
        worker.train_modal_client(adapter, round_spec, "worker-a", path, **options)


@pytest.mark.parametrize("mutation", ["new_key", "shape", "architecture", "excluded_memory"])
def test_post_training_layout_and_excluded_state_drift_rejected(prepared, tmp_path, monkeypatch, mutation):
    adapter, data, _ = prepared
    path = tmp_path / "data.json"
    round_spec = round_for(adapter, path, data)
    original_factory = type(adapter).fresh_model
    def factory(self, **options):
        model = original_factory(self, **options)
        original_train = model.train_generalizable_projection
        def train(*args, **kwargs):
            result = original_train(*args, **kwargs)
            if mutation == "new_key":
                model.state.feature_embedding_weights["undeclared:local-feature"] = [0.0] * round_spec.dimension
            elif mutation == "shape":
                first = next(iter(model.state.feature_embedding_weights))
                model.state.feature_embedding_weights[first].append(0.0)
            elif mutation == "architecture":
                model.state.architecture_version = "other-architecture"
            else:
                model.state.decoded_embeddings["memorized"] = [0.0] * round_spec.dimension
            return result
        model.train_generalizable_projection = train
        return model
    monkeypatch.setattr(type(adapter), "fresh_model", factory)
    with pytest.raises(ValueError):
        worker.train_modal_client(adapter, round_spec, "worker-a", path, compute_device="python", max_seconds=30)


def test_worker_uses_one_owned_data_snapshot(prepared, tmp_path, monkeypatch):
    adapter, data, _ = prepared
    path = tmp_path / "data.json"
    round_spec = round_for(adapter, path, data)
    original_factory = type(adapter).fresh_model
    def replace_data_file(self, **options):
        path.write_text("file changed after parsing")
        return original_factory(self, **options)
    monkeypatch.setattr(type(adapter), "fresh_model", replace_data_file)
    update, report = worker.train_modal_client(
        adapter, round_spec, "worker-a", path, compute_device="python", max_seconds=30,
    )
    assert update.local_data_sha256 == round_spec.clients[0].local_data_sha256
    assert report["local_data_sha256"] == update.local_data_sha256


@pytest.mark.parametrize("raw", [
    b'{"schema":"legal-federated-client-data/v1","schema":"legal-federated-client-data/v1"}',
    b'{"nested":{"weight":1,"weight":2}}',
    b'{"value":NaN}', b'{"value":Infinity}', b'not JSON',
])
def test_duplicate_or_nonfinite_json_rejected(tmp_path, raw):
    path = tmp_path / "invalid.json"
    path.write_bytes(raw)
    with pytest.raises(worker.FederatedWorkerError):
        worker._load_data(path, hashlib.sha256(raw).hexdigest())


def test_data_envelope_closed_fields_and_byte_bound(tmp_path, monkeypatch):
    path = tmp_path / "data.json"
    data = payload()
    data["weights"] = []
    digest = write_payload(path, data)
    with pytest.raises(worker.FederatedWorkerError, match="closed fields"):
        worker._load_data(path, digest)
    monkeypatch.setattr(worker, "MAX_CLIENT_DATA_BYTES", 10)
    with pytest.raises(worker.FederatedWorkerError, match="byte bound"):
        worker._load_data(path, digest)


def test_duck_typed_adapter_cannot_run_training(tmp_path):
    with pytest.raises(worker.FederatedWorkerError, match="exact verified"):
        worker.train_modal_client(object(), None, "worker-a", tmp_path / "missing")
