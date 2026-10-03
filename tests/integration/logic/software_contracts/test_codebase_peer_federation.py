"""Actual local peer processes and native source/queue/model owners; no fake telemetry."""
from copy import deepcopy
import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest

from ipfs_accelerate_py.p2p_tasks import codebase_peer_transport as transport
from ipfs_accelerate_py.p2p_tasks.codebase_federated_dispatch import CodebaseQueueDispatcher, CodebaseDispatchError
from ipfs_accelerate_py.p2p_tasks.task_queue import TaskQueue
from ipfs_datasets_py.logic.software_contracts import codebase_source_training as source
from ipfs_datasets_py.logic.software_contracts import codebase_federated_training as federation
from ipfs_datasets_py.logic.software_contracts import codebase_peer_dispatched_federation as peer
from ipfs_datasets_py.logic.software_contracts import codebase_federated_admission as admission
from ipfs_datasets_py.logic.software_contracts.codebase_resources import acquire_codebase_resources


@pytest.fixture(scope="module")
def current(tmp_path_factory):
    import duckdb
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
    from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
    from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
    from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
    from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
    root = tmp_path_factory.mktemp("peer-native"); repo = root / "repo"; repo.mkdir()
    for name, offset in (("a.py", 1), ("b.py", 2), ("c.py", 3), ("tune.py", 7), ("canary.py", 9)):
        (repo / name).write_text(f"def step(n: int) -> int:\n    return n + {offset}\n")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Peer Qualification", "-c", "user.email=peer@example.invalid",
                    "commit", "-qm", "source fixture"], check=True)
    cx = duckdb.connect(str(root / "source.duckdb"), config={"threads": 1, "memory_limit": "64MB"})
    store = DuckDBASTStore(connection=cx); cas = ImmutableCAS(root / "cas")
    index = RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store), artifacts=cas, catalog=CodebaseCatalog(store, cas))
    policy = admission.RetentionPolicy(index)
    registry = AutoencoderRegistry(root / "models.duckdb", root / "models", promotion_validator=policy); policy.bind(registry)
    queue = TaskQueue(str(root / "queue.duckdb"))
    value = SimpleNamespace(root=root, repo=repo, cx=cx, index=index, cas=cas, registry=registry, queue=queue, results=[])
    value.peers = {client: transport.CodebasePeerWorker(cas, root / (client + "-receipts"), profile_id="local-" + client)
                   for client in ("one", "two")}
    value.head = index.prepare_current(repo, repository_id="repository:peer", operation_id="capture", expected_head=None).head
    selections = [source.CodebaseTrainingSelection(path, "train" if path in ("a.py", "b.py", "c.py") else path[:-3])
                  for path in ("a.py", "b.py", "c.py", "tune.py", "canary.py")]
    value.parent = source.train_current_codebase_features(index, repo, expected_head=value.head, registry=registry,
        selections=selections, operation_id="root", epochs=1, learning_rate=.002, memory_mb=1024)
    value.clients = [federation.CodebaseFederatedClient("one", ("c.py",)), federation.CodebaseFederatedClient("two", ("a.py", "b.py"))]
    try:
        value.round = peer.train_current_peer_dispatched_codebase_round(index, repo, expected_head=value.head,
            registry=registry, base_version_id=value.parent.to_dict()["version_id"], clients=value.clients,
            operation_id="round", queue=queue, peers=value.peers)
        yield value
    finally:
        (root / "qualification.json").write_bytes(source._wire({"scope": "two local peer profiles; 8D structural fixture; no remote or 384D claim",
            "source_head": value.head.to_dict(), "parent": value.parent.to_dict(), "round": getattr(value, "round", None),
            "receipts": {k: p.receipts for k, p in value.peers.items()}, "controls": value.results,
            "native_default_host": True, "injected_telemetry": False, "model_provider_calls": 0}))
        queue.close(); registry.close(); cx.close()


def test_real_two_peer_round_exact_native_reduction(current):
    value = peer.load_peer_dispatched_codebase_round(current.index, current.registry, queue=current.queue,
                                                   artifact_cid=current.round["artifact_cid"])
    assert value == {key: val for key, val in current.round.items() if key != "artifact_cid"}
    receipts = [p.receipts[-1] for p in current.peers.values()]
    assert len({r["peer_pid"] for r in receipts}) == 2
    assert all(r["peer_pid"] != os.getpid() and r["numerical_invocations"] == 1 and r["delivery_verified"] for r in receipts)
    assert all(r["process"]["workspace_cleaned"] and r["process"]["returncode"] == 0 for r in receipts)
    row, saved = source._read_candidate(current.registry, current.round["version_id"], source.CodebaseFeatureTrainingLimits())
    parent = federation._parent(current.index, current.registry, current.parent.to_dict()["version_id"], source.CodebaseFeatureTrainingLimits())
    assert saved["state"]["parameters"] != parent["saved"]["state"]["parameters"]
    assert [(r["client_id"], r["sample_count"]) for r in saved["report"]["codebase_federation"]["round"]["clients"]] == [("one", 1), ("two", 2)]
    assert all(a["step"] == 0 for a in saved["state"]["adam"])
    assert not any(value["authority"].values())
    current.results.append({"control": "two-peer-native-FedAvg", "peer_pids": [r["peer_pid"] for r in receipts], "passed": True})


def _task(current):
    row = current.queue.list(status="completed", limit=10)[0]
    return row["payload"], row["model_name"]


def _context(current, selected):
    from contextlib import contextmanager
    @contextmanager
    def run():
        with acquire_codebase_resources(cpu_slots=3, memory_mb=2560, child_process_slots=3, timeout_seconds=30) as lease:
            deadline = time.monotonic() + 120
            with selected.execution_context(parent_lease=lease, cancel_event=lease.cancellation_signal,
                    remaining=lambda: deadline - time.monotonic(), memory_mb=1024, limits=source.CodebaseFeatureTrainingLimits()):
                yield
    return run()


def test_lost_response_restarts_actual_peer_without_refit(current):
    payload, model = _task(current)
    client = payload["declaration"]["payload"]["work_binding"]["client_id"]
    selected = transport.CodebasePeerWorker(current.cas, current.root / "lost-receipts", profile_id="lost-response-peer")
    queue = TaskQueue(str(current.root / "lost-queue.duckdb"))
    calls = []
    def handler(task):
        result = selected(task); calls.append(selected.receipts[-1])
        if len(calls) == 1:
            raise ConnectionError("test drops the actual peer response after exact result delivery")
        return result
    dispatcher = CodebaseQueueDispatcher(queue, handler)
    try:
        with _context(current, selected):
            with pytest.raises(ConnectionError, match="drops"):
                dispatcher.dispatch(payload, model)
            result = dispatcher.dispatch(payload, model)
            assert dispatcher.dispatch(payload, model) == result
        assert len(calls) == 2 and calls[0]["peer_pid"] != calls[1]["peer_pid"]
        assert [r["numerical_invocations"] for r in calls] == [1, 0]
        assert queue.list(limit=10)[0]["attempt"] == 2
        current.results.append({"control": "lost-response-actual-peer-restart-and-native-duplicate", "attempts": 2,
                               "numerical_invocations": [r["numerical_invocations"] for r in calls],
                               "receipts": calls, "passed": True})
    finally:
        queue.close()


def test_actual_unavailable_peer_process_cannot_complete(current, monkeypatch):
    from ipfs_datasets_py.logic.backends.codebase_process import SubprocessExecutor
    import subprocess
    real = SubprocessExecutor.execute
    def terminated(self, invocation, cancellation=None):
        original = self._popen
        def kill(*args, **kwargs):
            child = original(*args, **kwargs)
            os.killpg(child.pid, signal.SIGKILL)
            return child
        self._popen = kill
        try: return real(self, invocation, cancellation)
        finally: self._popen = original
    payload, model = _task(current)
    selected = current.peers[payload["declaration"]["payload"]["work_binding"]["client_id"]]
    queue = TaskQueue(str(current.root / "unavailable-queue.duckdb"))
    try:
        monkeypatch.setattr(SubprocessExecutor, "execute", terminated)
        with _context(current, selected):
            with pytest.raises(CodebaseDispatchError, match="process unavailable"):
                CodebaseQueueDispatcher(queue, selected).dispatch(payload, model)
        assert queue.list(limit=10)[0]["status"] != "completed"
        receipt = selected.receipts[-1]
        assert receipt["process"]["pid"] > 0 and receipt["process"]["returncode"] == -signal.SIGKILL
        current.results.append({"control": "actual-peer-process-SIGKILL", "pid": receipt["process"]["pid"], "passed": True})
    finally:
        queue.close()


def test_stale_queue_completion_after_actual_peer_result_refused(current):
    payload, model = _task(current)
    selected = current.peers[payload["declaration"]["payload"]["work_binding"]["client_id"]]
    queue = TaskQueue(str(current.root / "stale-queue.duckdb"))
    def handler(task):
        result = selected(task)
        queue.recover_expired_leases(now=time.time() + 1000)
        queue.claim(task_id=task["task_id"], worker_id="new-owner", lease_seconds=300)
        return result
    try:
        with _context(current, selected), pytest.raises(CodebaseDispatchError, match="stale|expired|replaced"):
            CodebaseQueueDispatcher(queue, handler).dispatch(payload, model)
        assert queue.list(limit=10)[0]["status"] != "completed"
        current.results.append({"control": "actual-peer-result-stale-queue-completion", "passed": True})
    finally:
        queue.close()


def test_historical_peer_record_cannot_rebind_profile_or_result(current):
    value = current.index.artifacts.get(current.round["artifact_cid"])
    snapshot = current.index.artifacts.get(value["deliveries"][0])
    receipt = json.loads(snapshot["canonical_json"]); receipt["profile_id"] = "other-peer"
    snapshot["canonical_json"] = source._wire(receipt).decode("ascii")
    value["deliveries"][0] = current.index.artifacts.put(snapshot)
    changed = current.index.artifacts.put(value)
    with pytest.raises(source.CodebaseFeatureTrainingError, match="binding differs"):
        peer.load_peer_dispatched_codebase_round(current.index, current.registry, queue=current.queue, artifact_cid=changed)


@pytest.mark.parametrize("raw", [b'\x00\x00\x00\x0d{"x":1,"x":2}', b'\x00\x00\x00\x09{"x":NaN}', b'\x00\x00\x00\xff{}'])
def test_strict_bounded_frames_reject_ambiguous_or_incomplete_json(raw):
    with pytest.raises(Exception): transport.frames(raw)


def test_peer_cannot_launch_without_inherited_owner(current):
    with pytest.raises(CodebaseDispatchError, match="live owner"):
        current.peers["one"]({})


def test_changed_source_refuses_before_any_peer_delivery(current):
    before = {key: len(value.receipts) for key, value in current.peers.items()}
    path = current.repo / "a.py"; original = path.read_bytes()
    path.write_bytes(original.replace(b"n + 1", b"n + 100"))
    try:
        with pytest.raises(Exception, match="current|snapshot|source|head"):
            peer.train_current_peer_dispatched_codebase_round(current.index, current.repo, expected_head=current.head,
                registry=current.registry, base_version_id=current.parent.to_dict()["version_id"], clients=current.clients,
                operation_id="changed-source", queue=current.queue, peers=current.peers)
        assert {key: len(value.receipts) for key, value in current.peers.items()} == before
    finally:
        path.write_bytes(original)


def test_wrong_model_reaches_actual_peer_but_cannot_complete(current):
    payload, model = _task(current)
    selected = current.peers[payload["declaration"]["payload"]["work_binding"]["client_id"]]
    queue = TaskQueue(str(current.root / "wrong-model-queue.duckdb"))
    try:
        with _context(current, selected), pytest.raises(CodebaseDispatchError, match="tool result failed"):
            CodebaseQueueDispatcher(queue, selected).dispatch(payload, model + "-wrong")
        assert queue.list(limit=10)[0]["status"] != "completed"
        assert selected.receipts[-1]["protocol_errors"]
    finally:
        queue.close()


def test_peer_transport_cannot_upgrade_changed_binary_reference(current):
    from ipfs_datasets_py.logic.software_contracts import codebase_federated_artifacts as artifacts
    row = current.queue.list(status="completed", limit=10)[0]
    changed = deepcopy(row["result"]); changed["update"]["sha256"] = "0" * 64
    with pytest.raises(Exception):
        artifacts.validate_codebase_artifact_result(row["payload"], changed, current.cas,
                                                   limits=source.CodebaseFeatureTrainingLimits())


def test_actual_peer_children_and_owned_leases_are_reaped(current):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import get_global_resource_scheduler
    receipts = [r for p in current.peers.values() for r in p.receipts]
    receipts += next(c["receipts"] for c in current.results if c["control"].startswith("lost-response"))
    owned = {r[key] for r in receipts for key in ("parent_lease_id", "delivery_lease_id", "peer_lease_id") if key in r}
    active = {r["lease_id"] for r in get_global_resource_scheduler().active_leases()}
    assert not owned & active
    assert all(not Path("/proc", str(r["process"]["pid"])).exists() for r in receipts)
    current.results.append({"control": "all-observed-peer-processes-and-native-leases-reaped", "lease_ids": sorted(owned), "passed": True})
