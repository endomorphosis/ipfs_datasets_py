"""Reference round connects private clients, binary updates and registry ownership."""

import hashlib
import json

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_federated_round as rounds
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_federated import ClientSpec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_federated_modal import load_modal_checkpoint


def prepare(tmp_path, dimension=8):
    from importlib import import_module
    namespace = import_module(
        "ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages."
        + ("legacy_v1" if dimension == 8 else "current_v2"))
    state = namespace.TrainingState(feature_embedding_weights={"existing": [1.0] * dimension})
    path = tmp_path / "base.json"
    state.save_json(path)
    adapter = load_modal_checkpoint(path, expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        runtime_version="legacy_v1" if dimension == 8 else "current_v2")
    round_spec = adapter.make_round("round-1",
        (ClientSpec("a", 1, "a" * 64), ClientSpec("b", 3, "b" * 64)),
        model_id="model-" + str(dimension), embedding_producer_sha256="e" * 64)
    return adapter, round_spec


def worker_stub(adapter, round_spec, client_id, _path, **_options):
    # Worker unit tests separately run both real trainers. Here controlled
    # changes test the complete artifact/aggregation/registry round boundary.
    state = adapter.fresh_state()
    state.feature_embedding_weights["existing"][0] += 4.0 if client_id == "a" else -2.0
    client = next(client for client in round_spec.clients if client.client_id == client_id)
    update = adapter.make_update_from_state(round_spec, client_id, state,
        local_steps=1, local_data_sha256=client.local_data_sha256)
    return update, {"qualified": False, "admitted": False, "client_id": client_id}


@pytest.mark.parametrize("dimension", [8, 384])
def test_round_persists_binary_updates_and_complete_same_lineage_aggregate(tmp_path, monkeypatch, dimension):
    adapter, round_spec = prepare(tmp_path, dimension)
    monkeypatch.setattr(rounds, "train_modal_client", worker_stub)
    result = rounds.execute_local_modal_round(adapter, round_spec,
        {"a": "data-a", "b": "data-b"}, tmp_path / "round")
    assert result.candidate.parameters["feature_embedding_weights"][0] == .5
    assert result.checkpoint_path.read_bytes().startswith(b"LIRMAECP")
    assert adapter.verify_materialization(round_spec, result.candidate, result.checkpoint_path) is True
    assert len(result.load_updates(round_spec)) == 2
    report = result.report
    assert report["complete"] and report["dimension"] == dimension
    assert report["qualified"] is report["publication_performed"] is False
    report["qualified"] = True
    assert result.report["qualified"] is False
    assert json.loads((tmp_path / "round" / "result.json").read_bytes()) == result.report


def test_registered_round_uses_real_modal_materialization_verifier_and_preserves_head(tmp_path, monkeypatch):
    from ipfs_datasets_py.duckdb_control.autoencoder_federated import (
        create_federated_run, complete_federated_run,
    )
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry

    adapter, round_spec = prepare(tmp_path)
    monkeypatch.setattr(rounds, "train_modal_client", worker_stub)
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        registry.register_variant("variant", round_spec.model_id,
                                  {"lineage_id": round_spec.lineage_id})
        artifact = registry.stage_artifact(adapter.path, expected_sha256=round_spec.base_sha256)
        parent = registry.register_version("base", round_spec.model_id, artifact)["version_id"]
        registry.initialize_head("head", round_spec.model_id, "main", parent)
        create_federated_run(registry, "create", "run", parent, round_spec)
        lease = registry.claim_run("claim", "run", "owner")["lease"]
        result = rounds.execute_local_modal_round(adapter, round_spec,
            {"a": "data-a", "b": "data-b"}, tmp_path / "round")
        receipt = complete_federated_run(registry, "complete", lease, round_spec,
            adapter.parameters, result.load_updates(round_spec), result.checkpoint_path,
            verify_checkpoint=adapter.verify_materialization)
        assert receipt["promoted"] is receipt["admitted"] is False
        assert registry.resolve_head(round_spec.model_id, "main")["version_id"] == parent


def test_failed_client_keeps_prior_artifacts_without_completed_round(tmp_path, monkeypatch):
    adapter, round_spec = prepare(tmp_path)

    def fails_second(*args, **options):
        if args[2] == "b":
            raise ValueError("client rejected layout drift")
        return worker_stub(*args, **options)

    monkeypatch.setattr(rounds, "train_modal_client", fails_second)
    directory = tmp_path / "round"
    with pytest.raises(ValueError, match="layout drift"):
        rounds.execute_local_modal_round(adapter, round_spec, {"a": "data-a", "b": "data-b"}, directory)
    assert (directory / "client-0000.update.bin").exists()
    assert not (directory / "aggregate.checkpoint.bin").exists()
    assert not (directory / "result.json").exists()


@pytest.mark.parametrize("paths", [{"a": "data"}, {"a": "data", "b": "data", "c": "data"}])
def test_round_requires_complete_approved_membership_before_outputs(tmp_path, paths):
    adapter, round_spec = prepare(tmp_path)
    with pytest.raises(ValueError, match="every approved client"):
        rounds.execute_local_modal_round(adapter, round_spec, paths, tmp_path / "round")
    assert not (tmp_path / "round").exists()


def test_existing_output_namespace_is_never_overwritten(tmp_path, monkeypatch):
    adapter, round_spec = prepare(tmp_path)
    directory = tmp_path / "round"
    directory.mkdir()
    (directory / "keep").write_text("existing")
    monkeypatch.setattr(rounds, "train_modal_client", lambda *_args, **_kw: pytest.fail("must not train"))
    with pytest.raises(FileExistsError):
        rounds.execute_local_modal_round(adapter, round_spec, {"a": "data-a", "b": "data-b"}, directory)
    assert (directory / "keep").read_text() == "existing"


def test_tampered_persisted_update_fails_owner_reload(tmp_path, monkeypatch):
    adapter, round_spec = prepare(tmp_path)
    monkeypatch.setattr(rounds, "train_modal_client", worker_stub)
    result = rounds.execute_local_modal_round(adapter, round_spec,
        {"a": "data-a", "b": "data-b"}, tmp_path / "round")
    path = tmp_path / "round" / "client-0000.update.bin"
    raw = bytearray(path.read_bytes())
    raw[-1] ^= 1
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        result.load_updates(round_spec)
