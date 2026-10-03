"""Actual native completion/restart recovery; no refit or manufactured delivery."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from tests.integration.logic.software_contracts.test_codebase_peer_federation import current
from ipfs_accelerate_py.p2p_tasks import codebase_peer_transport as transport
from ipfs_datasets_py.logic.software_contracts import codebase_peer_dispatched_federation as peer
from ipfs_datasets_py.logic.software_contracts import codebase_peer_recovery as recovery
from ipfs_datasets_py.logic.software_contracts import codebase_source_training as source


def _run_id(current):
    return "codebase-dispatched-fed:peer:" + current.round["policy_cid"]


def _recover(current, run_id=None):
    return recovery.recover_peer_dispatched_codebase_round(current.index, current.registry, queue=current.queue,
                                                          run_id=run_id or _run_id(current))


def _no_fit(monkeypatch):
    monkeypatch.setattr(source, "_worker", lambda *a, **k: pytest.fail("historical recovery fitted or inferred"))
    monkeypatch.setattr(transport.CodebasePeerWorker, "_deliver", lambda *a, **k: pytest.fail("historical recovery launched a peer"))


def _operation(current):
    run = current.registry.get_run(_run_id(current))
    operation = recovery._operation(recovery._identity(run)[0])
    with current.registry._transaction() as cx:
        row = cx.execute("SELECT payload_digest,receipt FROM autoencoder_control.operations WHERE operation_id=?", [operation]).fetchone()
    return run, operation, row


def test_final_sidecar_write_and_reply_loss_recover_same_cid_without_fit(current, monkeypatch):
    expected = deepcopy(current.round)
    target = current.cas.path_for(expected["artifact_cid"])
    target.unlink()  # Explicit fault: only the final test-fixture sidecar is missing.
    real_put = current.cas.put
    def fail_write(value):
        if value.get("schema") == peer.SCHEMA: raise OSError("injected final sidecar write loss")
        return real_put(value)
    with monkeypatch.context() as patch:
        _no_fit(patch); patch.setattr(current.cas, "put", fail_write)
        with pytest.raises(OSError, match="write loss"): _recover(current)
    assert not target.exists()
    def lose_reply(value):
        result = real_put(value)
        if value.get("schema") == peer.SCHEMA: raise ConnectionError("injected committed sidecar reply loss")
        return result
    with monkeypatch.context() as patch:
        _no_fit(patch); patch.setattr(current.cas, "put", lose_reply)
        with pytest.raises(ConnectionError, match="reply loss"): _recover(current)
    assert target.exists()
    with monkeypatch.context() as patch:
        _no_fit(patch)
        assert _recover(current) == expected
    current.results.append({"control": "durable-final-sidecar-write-and-reply-loss", "same_cid": expected["artifact_cid"], "passed": True})


def test_actual_native_completion_reply_loss_retries_without_sidecar_hint(current, monkeypatch):
    real_complete = peer.complete_federated_run
    captured = {}
    variant = current.parent.to_dict()["variant_id"]
    head_before = current.registry.resolve_head(variant, "main")
    def lose_reply(*args, **kwargs):
        captured["run_id"] = args[2]["run_id"]
        captured["completion"] = real_complete(*args, **kwargs)
        raise ConnectionError("injected reply loss after durable native completion")
    options = dict(expected_head=current.head, registry=current.registry, base_version_id=current.parent.to_dict()["version_id"],
                   clients=current.clients, operation_id="completion-reply-loss", queue=current.queue, peers=current.peers)
    with monkeypatch.context() as patch:
        patch.setattr(peer, "complete_federated_run", lose_reply)
        with pytest.raises(ConnectionError, match="durable native completion"):
            peer.train_current_peer_dispatched_codebase_round(current.index, current.repo, **options)
    assert current.registry.get_run_completion(captured["run_id"]) is not None
    assert current.registry.get_run(captured["run_id"])["status"] == "completed"
    assert current.registry.resolve_head(variant, "main") == head_before
    before = {key: len(value.receipts) for key, value in current.peers.items()}
    with monkeypatch.context() as patch:
        _no_fit(patch)
        result = peer.train_current_peer_dispatched_codebase_round(current.index, current.repo, **options)
        assert result == _recover(current, captured["run_id"])
    assert before == {key: len(value.receipts) for key, value in current.peers.items()}
    assert result["version_id"] == captured["completion"]["version_id"]
    assert current.registry.resolve_head(variant, "main") == head_before
    current.results.append({"control": "durable-native-completion-reply-loss", "recovered": result, "passed": True})


def test_prepared_population_without_native_completion_never_recovers(current, monkeypatch):
    captured = {}
    def stop(*args, **kwargs):
        captured["run_id"] = args[2]["run_id"]
        raise OSError("injected stop before native completion")
    with monkeypatch.context() as patch:
        patch.setattr(peer, "complete_federated_run", stop)
        with pytest.raises(OSError, match="before native completion"):
            peer.train_current_peer_dispatched_codebase_round(current.index, current.repo, expected_head=current.head,
                registry=current.registry, base_version_id=current.parent.to_dict()["version_id"], clients=current.clients,
                operation_id="prepared-only", queue=current.queue, peers=current.peers)
    run = current.registry.get_run(captured["run_id"])
    assert run["status"] == "failed" and run["lease"] is None
    operation = recovery._operation(recovery._identity(run)[0])
    with current.registry._transaction() as cx:
        assert cx.execute("SELECT count(*) FROM autoencoder_control.operations WHERE operation_id=?", [operation]).fetchone()[0] == 1
    with monkeypatch.context() as patch:
        _no_fit(patch)
        with pytest.raises(source.CodebaseFeatureTrainingError, match="not completed"): _recover(current, captured["run_id"])
    current.results.append({"control": "prepared-reference-does-not-create-completion", "run_id": captured["run_id"], "passed": True})


@pytest.mark.parametrize("fault", ["missing_reference", "changed_digest", "changed_fence"])
def test_missing_or_rebound_native_reference_refuses(current, monkeypatch, fault):
    run, operation, row = _operation(current)
    with current.registry._transaction() as cx:
        if fault == "missing_reference": cx.execute("DELETE FROM autoencoder_control.operations WHERE operation_id=?", [operation])
        elif fault == "changed_digest": cx.execute("UPDATE autoencoder_control.operations SET payload_digest=? WHERE operation_id=?", ["0" * 64, operation])
        else:
            receipt = json.loads(row[1]); receipt["identity"]["fence"] += 1
            cx.execute("UPDATE autoencoder_control.operations SET receipt=? WHERE operation_id=?", [json.dumps(receipt), operation])
    try:
        with monkeypatch.context() as patch:
            _no_fit(patch)
            with pytest.raises(source.CodebaseFeatureTrainingError): _recover(current)
    finally:
        with current.registry._transaction() as cx:
            if fault == "missing_reference": cx.execute("INSERT INTO autoencoder_control.operations VALUES (?,?,?)", [operation, *row])
            else: cx.execute("UPDATE autoencoder_control.operations SET payload_digest=?,receipt=? WHERE operation_id=?", [*row, operation])


@pytest.mark.parametrize("fault", ["missing", "changed_bytes"])
def test_missing_or_changed_manifest_body_refuses(current, monkeypatch, fault):
    _, _, row = _operation(current)
    descriptor = json.loads(row[1])["manifest"]; path = current.registry.artifact_path(descriptor); raw = path.read_bytes()
    if fault == "missing": path.unlink()
    else: path.write_bytes(raw + b" ")
    try:
        with monkeypatch.context() as patch:
            _no_fit(patch)
            with pytest.raises(Exception): _recover(current)
    finally:
        path.write_bytes(raw)


def test_native_operation_rebinding_cannot_overwrite_population(current):
    run, operation, row = _operation(current)
    descriptor = json.loads(row[1])["manifest"]
    payload = {"identity": recovery._identity(run)[0], "manifest": {**descriptor, "sha256": "f" * 64}, "lease": run["lease"]}
    with pytest.raises(Exception, match="different payload"):
        current.registry._mutate(operation, recovery.COMMAND, payload, lambda _: pytest.fail("rebinding apply ran"))
    assert _operation(current)[2] == row


@pytest.mark.parametrize("fault", ["source_head", "delivery_population"])
def test_resealed_native_reference_cannot_rebind_source_or_population(current, fault):
    run, operation, row = _operation(current)
    receipt = json.loads(row[1]); original = receipt["manifest"]
    manifest = json.loads(current.registry.artifact_path(original).read_bytes())
    if fault == "source_head": manifest["source_head"]["generation"] += 1
    else: manifest["deliveries"] = [manifest["deliveries"][0]] * len(manifest["deliveries"])
    path = current.root / ("resealed-" + fault + ".json"); path.write_bytes(source._wire(manifest))
    descriptor = current.registry.stage_artifact(path)
    receipt["manifest"] = descriptor
    payload = {"identity": recovery._identity(run)[0], "manifest": descriptor, "lease": run["lease"]}
    digest = current.registry._command_digest(operation, recovery.COMMAND, payload)
    with current.registry._transaction() as cx:
        cx.execute("UPDATE autoencoder_control.operations SET payload_digest=?,receipt=? WHERE operation_id=?",
                   [digest, json.dumps(receipt), operation])
    try:
        with pytest.raises(source.CodebaseFeatureTrainingError, match="source|receipt|cohort"):
            _recover(current)
    finally:
        with current.registry._transaction() as cx:
            cx.execute("UPDATE autoencoder_control.operations SET payload_digest=?,receipt=? WHERE operation_id=?", [*row, operation])


def test_cold_process_recovers_from_native_run_without_warmed_receipts(current):
    # Last test: release native owners before the separate process opens them.
    current.queue.close(); current.registry.close(); current.cx.close()
    program = r'''
import json,sys
from pathlib import Path
import duckdb
from ipfs_accelerate_py.p2p_tasks.task_queue import TaskQueue
from ipfs_accelerate_py.p2p_tasks import codebase_peer_transport as transport
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.logic.software_contracts import codebase_peer_recovery as recovery,codebase_source_training as source
def forbidden(*a,**k):raise AssertionError('cold recovery executed numerical or peer work')
source._worker=forbidden;transport.CodebasePeerWorker._deliver=forbidden
root=Path(sys.argv[1]);cas=ImmutableCAS(root/'cas')
cx=duckdb.connect(str(root/'source.duckdb'),config={'threads':1,'memory_limit':'64MB'})
store=DuckDBASTStore(connection=cx);index=RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store),artifacts=cas,catalog=CodebaseCatalog(store,cas))
registry=AutoencoderRegistry(root/'models.duckdb',root/'models');queue=TaskQueue(str(root/'queue.duckdb'))
try:
 value=recovery.recover_peer_dispatched_codebase_round(index,registry,queue=queue,run_id=sys.argv[2])
 Path(sys.argv[3]).write_text(json.dumps(value,sort_keys=True))
finally:queue.close();registry.close();cx.close()
'''
    output = current.root / "cold-recovery.json"
    completed = subprocess.run([sys.executable, "-c", program, str(current.root), _run_id(current), str(output)],
                               capture_output=True, text=True, timeout=120)
    assert completed.returncode == 0, completed.stderr[-4000:]
    assert json.loads(output.read_text()) == current.round
    current.results.append({"control": "cold-process-native-owner-recovery", "same_cid": current.round["artifact_cid"], "passed": True})
