"""Explicit simulated container contracts; never Docker/native qualification.

No process, cgroup, daemon, Docker command or native grant is created by these
tests. No repository process-security helper is imported. Temporary helper
source verifies provenance checks; real container qualification is separate.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import socket
from types import ModuleType

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_kernel_custody as kernel
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_container_boundary as boundary
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_kernel_custody import (
    MOUNT, ROOT, WORKER, SimulatedCgroupFS,
)


CID, SOURCE, REQUEST, NONCE = (character * 64 for character in "1234")
IMAGE, DAEMON_SHA = "sha256:" + "5" * 64, "6" * 64


class SimulatedPeer:
    simulation = True

    def __init__(self):
        self.active = True
        self.record = dict(pid=200, uid=1000, gid=1000, start_time_ticks=333,
            socket_identity=(3, 4, 1000, 0o140600, 0, 1, 1),
            executable="/usr/bin/dockerd", executable_identity=(8, 9, 0, 0o100755, 123, 1, 1),
            executable_sha256=DAEMON_SHA, pid_namespace=(7, 20), scanner_pid_namespace=(7, 20))

    def peer(self, connection, path):
        if not self.active:
            raise OSError("simulated closed daemon connection")
        return copy.deepcopy(self.record)


class SimulatedProcessSecurity:
    simulation = True

    def __init__(self, fs, worker):
        self.fs, self.worker = fs, worker
        self.capture_calls = 0
        self.namespace_empty, self.container_cgroup_empty = False, False
        self.quiescence_calls = 0
        self.capture_fault = None
        self.on_quiescence = None

    def capture_linux_process_scope(self, pid):
        self.capture_calls += 1
        process = self.fs.process(pid)
        if process is None or process["state"] == "Z":
            raise OSError("simulated process disappeared before capture")
        obs = self.worker.observe()
        matching = [group for path, group in self.worker._groups.items()
                    if self.worker._membership(Path(path)) == process["membership"]]
        if len(matching) != 1:
            raise OSError("simulated init outside frozen worker")
        directory = matching[0]["identity"]
        mount = obs["mount_directory_identity"]
        events = matching[0]["control_identities"]["cgroup.events"]
        value = dict(schema="ipfs_accelerate_py/agent-supervisor/linux-process-scope@1",
            pid=pid, start_time_ticks=process["birth"], boot_id=obs["boot_id"],
            pid_namespace_device=7, pid_namespace_inode=21,
            cgroup_relative_path=process["membership"].lstrip("/"),
            cgroup_mount_device=mount["device"], cgroup_mount_inode=mount["inode"],
            cgroup_directory_device=directory["device"], cgroup_directory_inode=directory["inode"],
            cgroup_events_device=events["device"], cgroup_events_inode=events["inode"])
        if self.capture_fault:
            self.capture_fault(value, self.capture_calls)
        value["identity_id"] = "sha256:" + hashlib.sha256(json.dumps(
            value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return value

    def validate_linux_process_scope(self, value):
        return copy.deepcopy(value)

    def linux_process_scope_quiescent(self, scope):
        self.quiescence_calls += 1
        if self.on_quiescence:
            self.on_quiescence(self.quiescence_calls)
        return self.namespace_empty and self.container_cgroup_empty


@pytest.fixture
def setup(request):
    fs = SimulatedCgroupFS()
    fs.group(ROOT, processes="101", tasks=4, memory=512)
    fs.text("memory.max", "512")
    if getattr(request, "param", False):
        fs.text("cgroup.procs", "")
        fs.text("cgroup.events", "populated 1\nfrozen 0")
        fs.group(WORKER / "container")
        fs.processes[100]["membership"] = "/unit/worker/container"
    fs.processes[101] = dict(pid=101, birth=199, state="S", membership="/unit")
    def bind(path, root, memory):
        return kernel.bind_cgroup(path, expected_root=root, expected_owner_uid=1000,
            required_memory_max=memory, required_pids_max=8, required_cpu_quota_us=100000,
            required_cpu_period_us=100000, allow_drain=True, _backend=fs)
    controller, worker = bind(ROOT, MOUNT, 1024), bind(WORKER, ROOT, 512)
    peer_backend = SimulatedPeer()
    peer_args = dict(socket_path="/run/user/1000/docker.sock", expected_pid=200,
        expected_start_time_ticks=333, expected_executable="/usr/bin/dockerd",
        expected_executable_sha256=DAEMON_SHA, _backend=peer_backend)
    peer = boundary.DirectDockerPeer(object(), **peer_args)
    helpers = SimulatedProcessSecurity(fs, worker)
    adapter = boundary.ProcessSecurityAdapter(None, expected_path="/simulated/process_security.py",
        expected_sha256="7" * 64, _backend=helpers)
    inspection = [dict(Id=CID, Name="/legal-ir-fixture", Image=IMAGE,
        Config=dict(Labels={"ipfs_datasets.source_sha256": SOURCE,
                           "ipfs_datasets.request_sha256": REQUEST,
                           "ipfs_datasets.nonce": NONCE}),
        HostConfig=dict(PidMode=""), State=dict(Pid=100, Running=True, Dead=False,
            Restarting=False, Status="running", Paused=False, StartedAt="2026-10-16T00:00:00Z"))]
    values = dict(container_id=CID, container_name="legal-ir-fixture", image_id=IMAGE,
        source_sha256=SOURCE, request_sha256=REQUEST, nonce=NONCE,
        docker_inspect=lambda _: copy.deepcopy(inspection), process_security=adapter,
        daemon_peer=peer, owner_pid=101, native_memory_bytes=768, native_child_process_slots=2)
    try:
        yield dict(fs=fs, controller=controller, worker=worker, peer=peer,
                   peer_backend=peer_backend, peer_args=peer_args, helpers=helpers,
                   adapter=adapter, inspection=inspection, values=values)
    finally:
        worker.close()
        controller.close()
    assert not fs.handles


def attest(setup, **changes):
    return boundary.attest_container_execution(setup["controller"], setup["worker"],
                                               **(setup["values"] | changes))


def empty_worker(setup):
    fs = setup["fs"]
    fs.text("cgroup.procs", "")
    fs.text("cgroup.events", "populated 0\nfrozen 0")
    fs.text("pids.current", "0")
    fs.text("memory.current", "0")
    fs.processes[100]["state"] = "Z"


def test_simulation_binds_exact_identity_without_any_admission_or_release(setup):
    bound = attest(setup)
    receipt = bound.receipt()
    assert receipt["container_id"] == CID
    assert receipt["kernel_scope"]["start_time_ticks"] == 99
    assert receipt["host_pid_mapping"] == "direct_dockerd_same_scanner_pid_namespace"
    assert setup["helpers"].capture_calls == 2
    assert receipt["simulation"] is receipt["observation_only"] is True
    for key in ("native_admission", "admitted", "Lean_admitted",
                "native_ownership_authenticated", "container_semantic_qualification"):
        assert receipt[key] is False
    assert not hasattr(bound, "release") and not hasattr(bound, "__exit__")
    assert setup["fs"].writes == []


def test_historical_receipt_is_a_copy_and_cannot_reconstitute_custody(setup):
    bound = attest(setup)
    receipt = bound.receipt()
    receipt["kernel_scope"]["pid"] = 999
    assert bound.receipt()["kernel_scope"]["pid"] == 100
    with pytest.raises(kernel.KernelCustodyError):
        boundary.BoundContainerExecution(receipt, setup["controller"], setup["worker"],
            setup["adapter"], receipt["kernel_scope"], receipt)
    with pytest.raises(kernel.KernelCustodyError, match="held controller"):
        boundary.attest_container_execution(setup["controller"].observe(),
                                            setup["worker"], **setup["values"])


@pytest.mark.parametrize("setup", [True], indirect=True)
def test_exact_init_may_live_in_an_original_frozen_worker_descendant(setup):
    bound = attest(setup)
    scope = bound.receipt()["kernel_scope"]
    assert scope["cgroup_relative_path"] == "unit/worker/container"
    assert scope["cgroup_directory_inode"] != setup["worker"].observe()["directory_identity"]["inode"]
    setup["worker"].drain(timeout_seconds=1)  # Explicit simulated caller cleanup.
    setup["helpers"].namespace_empty = setup["helpers"].container_cgroup_empty = True
    assert bound.quiescent() is True


@pytest.mark.parametrize("section,key,value", [
    (None, "Id", "8" * 64), (None, "Name", "/another"), (None, "Image", "sha256:" + "8" * 64),
    ("HostConfig", "PidMode", "host"), ("HostConfig", "PidMode", "container:other"),
    ("State", "Pid", 0), ("State", "Pid", True), ("State", "Pid", -1),
    ("State", "Running", False), ("State", "Dead", True), ("State", "Restarting", True),
    ("State", "Status", "exited"), ("State", "Status", "created"),
    ("State", "StartedAt", "0001-01-01T00:00:00Z"), ("State", "StartedAt", ""),
    ("State", "Paused", True),
])
def test_wrong_container_identity_or_execution_state_fails_closed(setup, section, key, value):
    target = setup["inspection"][0] if section is None else setup["inspection"][0][section]
    target[key] = value
    with pytest.raises(kernel.KernelCustodyError):
        attest(setup)
    assert setup["fs"].writes == []


@pytest.mark.parametrize("label", boundary._LABELS)
def test_source_request_nonce_labels_are_each_required_exactly(setup, label):
    setup["inspection"][0]["Config"]["Labels"][label] = "9" * 64
    with pytest.raises(kernel.KernelCustodyError, match="labels differ"):
        attest(setup)


def test_paused_container_can_bind_before_productive_barrier(setup):
    setup["inspection"][0]["State"].update(Status="paused", Paused=True)
    assert attest(setup).receipt()["execution"]["paused"] is True


@pytest.mark.parametrize("key,value", [("Pid", 102), ("StartedAt", "2026-10-16T00:01:00Z")])
def test_inspect_capture_inspect_race_is_closed(setup, key, value):
    calls = []
    def inspect(cid):
        calls.append(cid)
        result = copy.deepcopy(setup["inspection"])
        if len(calls) == 2:
            result[0]["State"][key] = value
        return result
    with pytest.raises(kernel.KernelCustodyError, match="changed during process-scope"):
        attest(setup, docker_inspect=inspect)
    assert calls == [CID, CID]


def test_zero_pid_after_executed_container_does_not_mint_posthoc_binding(setup):
    calls = []
    def inspect(cid):
        calls.append(cid)
        result = copy.deepcopy(setup["inspection"])
        if len(calls) == 2:
            result[0]["State"].update(Pid=0, Running=False, Status="exited")
        return result
    with pytest.raises(kernel.KernelCustodyError, match="zero PID"):
        attest(setup, docker_inspect=inspect)


def test_disappearance_before_capture_never_becomes_inert_success(setup):
    def inspect(cid):
        del setup["fs"].processes[100]
        return copy.deepcopy(setup["inspection"])
    with pytest.raises(OSError, match="disappeared"):
        attest(setup, docker_inspect=inspect)


@pytest.mark.parametrize("field,value", [
    ("pid_namespace_inode", 20), ("cgroup_relative_path", "foreign"),
    ("cgroup_mount_inode", 999), ("cgroup_directory_inode", 999),
    ("cgroup_events_inode", 999), ("start_time_ticks", 100),
    ("boot_id", "another-boot"), ("pid", 999),
])
def test_scope_must_match_host_birth_private_namespace_and_held_subtree(setup, field, value):
    setup["helpers"].capture_fault = lambda record, _: record.update({field: value})
    with pytest.raises(kernel.KernelCustodyError):
        attest(setup)


def test_birth_change_between_capture_and_confirmation_is_rejected(setup):
    def fault(record, call):
        if call == 2:
            record["start_time_ticks"] += 1
    setup["helpers"].capture_fault = fault
    with pytest.raises(kernel.KernelCustodyError, match="birth, namespace or cgroup changed"):
        attest(setup)


@pytest.mark.parametrize("field,value", [
    ("pid", 201), ("start_time_ticks", 334),
    ("executable", "/tmp/dockerd"), ("executable_sha256", "9" * 64),
    ("pid_namespace", (7, 99)),
])
def test_direct_daemon_identity_and_pid_mapping_must_remain_exact(setup, field, value):
    setup["peer_backend"].record[field] = value
    with pytest.raises(kernel.KernelCustodyError):
        attest(setup)


def test_rootless_daemon_in_another_pid_namespace_is_refused_before_inspect(setup):
    setup["peer_backend"].record["pid_namespace"] = (7, 99)
    with pytest.raises(kernel.KernelCustodyError, match="not a host mapping"):
        boundary.DirectDockerPeer(object(), **setup["peer_args"])
    assert setup["helpers"].capture_calls == 0


def test_closed_socket_and_proxy_executable_are_refused(setup):
    setup["peer_backend"].active = False
    with pytest.raises(kernel.KernelCustodyError, match="unavailable"):
        attest(setup)
    args = setup["peer_args"] | dict(expected_executable="/usr/bin/docker-proxy")
    with pytest.raises(kernel.KernelCustodyError, match="exact direct dockerd"):
        boundary.DirectDockerPeer(object(), **args)


def test_wrong_controller_anchor_or_closed_binding_is_refused(setup):
    setup["controller"].close()
    with pytest.raises(kernel.KernelCustodyError, match="closed"):
        attest(setup)


def test_worker_anchored_outside_its_actual_controller_is_refused(setup):
    with kernel.bind_cgroup(WORKER, expected_root=MOUNT, expected_owner_uid=1000,
            required_memory_max=512, required_pids_max=8, required_cpu_quota_us=100000,
            required_cpu_period_us=100000, _backend=setup["fs"]) as wrong_anchor:
        with pytest.raises(kernel.KernelCustodyError, match="ancestry anchor"):
            boundary.attest_container_execution(setup["controller"], wrong_anchor,
                                                 **setup["values"])


@pytest.mark.parametrize("namespace_empty,cgroup_empty", [(False, False), (True, False), (False, True)])
def test_namespace_and_container_cgroup_quiescence_are_both_required(setup, namespace_empty, cgroup_empty):
    bound = attest(setup)
    empty_worker(setup)
    setup["helpers"].namespace_empty = namespace_empty
    setup["helpers"].container_cgroup_empty = cgroup_empty
    assert bound.quiescent() is False
    assert setup["fs"].writes == []


def test_empty_namespace_and_container_cgroup_do_not_hide_other_worker_processes(setup):
    bound = attest(setup)
    setup["helpers"].namespace_empty = setup["helpers"].container_cgroup_empty = True
    assert bound.quiescent() is False
    assert setup["helpers"].quiescence_calls == 0


def test_successful_quiescence_does_not_release_or_drain_native_or_kernel_state(setup):
    bound = attest(setup)
    empty_worker(setup)
    setup["helpers"].namespace_empty = setup["helpers"].container_cgroup_empty = True
    assert bound.quiescent() is True
    assert setup["helpers"].quiescence_calls == 2
    assert not hasattr(bound, "release") and not hasattr(bound, "drain")
    assert setup["fs"].writes == []


def test_cleanup_observation_does_not_require_original_root_owner_alive(setup):
    bound = attest(setup)
    empty_worker(setup)
    setup["fs"].text("cgroup.procs", "", group=ROOT)
    setup["fs"].text("cgroup.events", "populated 0\nfrozen 0", group=ROOT)
    del setup["fs"].processes[101]
    setup["helpers"].namespace_empty = setup["helpers"].container_cgroup_empty = True
    assert bound.quiescent() is True


@pytest.mark.parametrize("repopulate_at", [1, 2])
def test_worker_repopulation_between_quiescence_reads_is_refused(setup, repopulate_at):
    bound = attest(setup)
    empty_worker(setup)
    helpers = setup["helpers"]
    helpers.namespace_empty = helpers.container_cgroup_empty = True
    def repopulate(call):
        if call == repopulate_at:
            setup["fs"].text("cgroup.procs", "102")
            setup["fs"].text("cgroup.events", "populated 1\nfrozen 0")
            setup["fs"].text("pids.current", "1")
    helpers.on_quiescence = repopulate
    assert bound.quiescent() is False


def test_closed_held_scope_cannot_be_replaced_by_cached_json_success(setup):
    bound = attest(setup)
    empty_worker(setup)
    setup["helpers"].namespace_empty = setup["helpers"].container_cgroup_empty = True
    setup["worker"].close()
    assert bound.quiescent() is False


def test_unknown_namespace_quiescence_keeps_cleanup_unqualified(setup, monkeypatch):
    bound = attest(setup)
    empty_worker(setup)
    def unknown(_):
        raise OSError("simulated permission loss during namespace scan")
    monkeypatch.setattr(setup["helpers"], "linux_process_scope_quiescent", unknown)
    assert bound.quiescent() is False
    assert setup["fs"].writes == []


def test_unmarked_backend_and_unverified_source_module_are_refused():
    with pytest.raises(kernel.KernelCustodyError, match="explicitly identify simulation"):
        boundary.ProcessSecurityAdapter(None, expected_path="/source.py", expected_sha256="1" * 64,
                                        _backend=object())
    with pytest.raises(kernel.KernelCustodyError, match="actual process-security module"):
        boundary.ProcessSecurityAdapter({}, expected_path="/source.py", expected_sha256="1" * 64)


@pytest.fixture
def helper_source(tmp_path):
    """Small temporary helper code, not a repository source import or proof."""
    path = tmp_path / "process_security.py"
    raw = ("def capture_linux_process_scope(pid):\n    return {'pid': pid}\n"
           "def validate_linux_process_scope(record):\n    return dict(record)\n"
           "def linux_process_scope_quiescent(record):\n    return False\n").encode()
    path.write_bytes(raw)
    module = ModuleType("_explicit_temporary_helper_source")
    module.__file__ = str(path)
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module, path, hashlib.sha256(raw).hexdigest()


def test_adapter_requires_exact_live_module_origin_and_source_digest(helper_source):
    module, path, digest = helper_source
    adapter = boundary.ProcessSecurityAdapter(module, expected_path=path, expected_sha256=digest)
    assert adapter.simulation is False
    assert adapter.capture(12) == {"pid": 12}
    assert adapter.quiescent({"pid": 12}) is False
    with pytest.raises(kernel.KernelCustodyError, match="source origin or SHA256 differs"):
        boundary.ProcessSecurityAdapter(module, expected_path=path, expected_sha256="f" * 64)


def test_changed_helper_source_invalidates_previously_constructed_adapter(helper_source):
    module, path, digest = helper_source
    adapter = boundary.ProcessSecurityAdapter(module, expected_path=path, expected_sha256=digest)
    path.write_text(path.read_text() + "# source drift\n")
    with pytest.raises(kernel.KernelCustodyError, match="source origin or SHA256 differs"):
        adapter.capture(12)


def test_mixed_simulated_and_real_adapter_cannot_attest_actual_custody(setup, helper_source):
    module, path, digest = helper_source
    adapter = boundary.ProcessSecurityAdapter(module, expected_path=path, expected_sha256=digest)
    with pytest.raises(kernel.KernelCustodyError, match="cannot be mixed"):
        attest(setup, process_security=adapter)


@pytest.mark.parametrize("alias", ["file", "parent", "dotdot", "double_slash"])
def test_source_aliases_are_refused(helper_source, tmp_path, alias):
    module, original, digest = helper_source
    if alias == "file":
        path = tmp_path / "linked.py"
        path.symlink_to(original)
    elif alias == "parent":
        directory = tmp_path / "linked-parent"
        directory.symlink_to(tmp_path, target_is_directory=True)
        path = directory / original.name
    elif alias == "dotdot":
        path = str(tmp_path) + "/missing/../" + original.name
    else:
        path = "/" + str(original)
    module.__file__ = str(path)
    with pytest.raises(kernel.KernelCustodyError):
        boundary.ProcessSecurityAdapter(module, expected_path=path, expected_sha256=digest)


@pytest.mark.parametrize("kind", ["directory", "hardlink", "oversize"])
def test_source_must_be_bounded_regular_and_single_link(helper_source, tmp_path, kind):
    module, original, digest = helper_source
    path = tmp_path / "invalid.py"
    if kind == "directory":
        path.mkdir()
    elif kind == "hardlink":
        path.hardlink_to(original)
    else:
        with path.open("wb") as stream:
            stream.truncate(2 * 1024 * 1024 + 1)
    module.__file__ = str(path)
    with pytest.raises(kernel.KernelCustodyError, match="bounded single-link regular"):
        boundary.ProcessSecurityAdapter(module, expected_path=path, expected_sha256=digest)


def test_pipe_source_descriptor_is_refused_without_creating_a_filesystem_fifo(helper_source, monkeypatch):
    module, path, digest = helper_source
    read_descriptor, write_descriptor = os.pipe()
    try:
        monkeypatch.setattr(boundary, "_open_unaliased_source", lambda _: os.dup(read_descriptor))
        with pytest.raises(kernel.KernelCustodyError, match="bounded single-link regular"):
            boundary.ProcessSecurityAdapter(module, expected_path=path, expected_sha256=digest)
    finally:
        os.close(read_descriptor)
        os.close(write_descriptor)


@pytest.mark.parametrize("fault", ["missing", "foreign_function", "foreign_module", "nonfunction"])
def test_malformed_helper_function_bindings_are_refused(helper_source, fault):
    module, path, digest = helper_source
    name = "capture_linux_process_scope"
    if fault == "missing":
        delattr(module, name)
    elif fault == "foreign_function":
        code = compile("def capture_linux_process_scope(pid): return {}", "/foreign/source.py", "exec")
        exec(code, module.__dict__)
    elif fault == "foreign_module":
        getattr(module, name).__module__ = "another_module"
    else:
        setattr(module, name, lambda: None)
    with pytest.raises(kernel.KernelCustodyError, match="function source differs"):
        boundary.ProcessSecurityAdapter(module, expected_path=path, expected_sha256=digest)


def test_source_mutation_during_hash_is_refused(helper_source, monkeypatch):
    module, path, digest = helper_source
    original_read = boundary.os.read
    changed = []
    def modifying_read(descriptor, maximum):
        value = original_read(descriptor, maximum)
        if not changed:
            changed.append(True)
            path.write_text(path.read_text() + "# edit during stream\n")
        return value
    monkeypatch.setattr(boundary.os, "read", modifying_read)
    with pytest.raises(kernel.KernelCustodyError, match="changed while hashed"):
        boundary.ProcessSecurityAdapter(module, expected_path=path, expected_sha256=digest)


@pytest.fixture
def local_idle_socketpair():
    """Real anonymous local sockets; no filesystem special file or process."""
    client, peer = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    with client, peer:
        client.settimeout(0.1)
        yield client, peer


def test_real_idle_socket_with_positive_timeout_never_blocks_in_recv(local_idle_socketpair):
    """Exercise real Python readiness/peek, not a Docker identity attestation."""
    client, _ = local_idle_socketpair
    boundary._require_idle_connection(client)
    assert client.gettimeout() == 0.1


@pytest.mark.parametrize("peer_state", ["eof", "pending_data"])
def test_real_dedicated_socket_refuses_eof_or_pending_data(local_idle_socketpair, peer_state):
    client, peer = local_idle_socketpair
    if peer_state == "eof":
        peer.shutdown(socket.SHUT_RDWR)
    else:
        peer.sendall(b"unexpected response")
    with pytest.raises(kernel.KernelCustodyError, match="closed or has unexpected pending data"):
        boundary._require_idle_connection(client)


def remove_simulated_group(fs, path):
    """Remove named simulated paths; original held handles remain unchanged."""
    for name in list(fs.nodes):
        candidate = Path(name)
        if candidate == path or path in candidate.parents:
            del fs.nodes[name]


@pytest.mark.parametrize("setup", [True], indirect=True)
def test_deleted_executed_child_allows_cleanup_observation_but_no_productive_adoption(setup):
    bound = attest(setup)
    empty_worker(setup)
    remove_simulated_group(setup["fs"], WORKER / "container")
    helpers = setup["helpers"]
    helpers.namespace_empty = helpers.container_cgroup_empty = True
    with pytest.raises(kernel.KernelCustodyError, match="no implicit adoption"):
        setup["worker"].observe()
    with pytest.raises(kernel.KernelCustodyError):
        setup["controller"].observe()
    observation = setup["worker"].observe_cleanup()
    assert observation["populated"] is False
    assert observation["cleanup_only"] is True
    assert observation["productive_observation"] is observation["frozen_tree_revalidated"] is False
    assert observation["native_admission"] is observation["admitted"] is observation["Lean_admitted"] is False
    assert "process_ids" not in observation and "memory_current_bytes" not in observation
    assert bound.quiescent() is True
    assert helpers.quiescence_calls == 2
    assert setup["fs"].writes == []


@pytest.mark.parametrize("setup", [True], indirect=True)
def test_deleted_container_child_still_requires_original_namespace_empty(setup):
    bound = attest(setup)
    empty_worker(setup)
    remove_simulated_group(setup["fs"], WORKER / "container")
    setup["helpers"].container_cgroup_empty = True
    setup["helpers"].namespace_empty = False
    assert setup["worker"].observe_cleanup()["populated"] is False
    assert bound.quiescent() is False


def test_new_populated_descendant_cannot_be_hidden_by_cleanup_topology_tolerance(setup):
    bound = attest(setup)
    empty_worker(setup)
    fs = setup["fs"]
    fs.group(WORKER / "new", processes="102")
    fs.processes[102] = dict(pid=102, birth=300, state="S", membership="/unit/worker/new")
    fs.text("cgroup.events", "populated 1\nfrozen 0")
    setup["helpers"].namespace_empty = setup["helpers"].container_cgroup_empty = True
    with pytest.raises(kernel.KernelCustodyError, match="no implicit adoption"):
        setup["worker"].observe()
    assert setup["worker"].observe_cleanup()["populated"] is True
    assert bound.quiescent() is False
    assert setup["fs"].writes == []


@pytest.mark.parametrize("fault", ["leaf", "events", "memory_control", "root", "mount_directory", "mount", "boot"])
def test_cleanup_observation_still_requires_exact_live_kernel_identities(setup, fault):
    bound = attest(setup)
    empty_worker(setup)
    setup["helpers"].namespace_empty = setup["helpers"].container_cgroup_empty = True
    fs = setup["fs"]
    if fault == "leaf":
        fs.add(WORKER, directory=True)
    elif fault == "events":
        fs.add(WORKER / "cgroup.events", text="populated 0\nfrozen 0")
    elif fault == "memory_control":
        fs.add(WORKER / "memory.max", text="512")
    elif fault == "root":
        fs.add(ROOT, directory=True)
    elif fault == "mount_directory":
        fs.add(MOUNT, directory=True)
    elif fault == "mount":
        fs.mount_record["mount_id"] += 1
    else:
        fs.boot = "another-boot"
    with pytest.raises(kernel.KernelCustodyError):
        setup["worker"].observe_cleanup()
    assert bound.quiescent() is False


def test_deleted_worker_itself_never_becomes_a_successful_cleanup_observation(setup):
    bound = attest(setup)
    empty_worker(setup)
    setup["helpers"].namespace_empty = setup["helpers"].container_cgroup_empty = True
    remove_simulated_group(setup["fs"], WORKER)
    with pytest.raises(kernel.KernelCustodyError, match="cleanup observation unavailable"):
        setup["worker"].observe_cleanup()
    assert bound.quiescent() is False


def test_changed_limits_are_not_productive_budget_approval_during_cleanup(setup):
    fs, worker = setup["fs"], setup["worker"]
    fs.text("memory.max", "999")
    with pytest.raises(kernel.KernelCustodyError, match="effective cgroup limits differ"):
        worker.observe()
    cleanup = worker.observe_cleanup()
    assert cleanup["populated"] is True
    assert cleanup["cleanup_only"] is True
    assert cleanup["productive_observation"] is cleanup["native_admission"] is False
    assert "memory_max_bytes" not in cleanup


def test_population_change_between_cleanup_reads_is_refused(setup, monkeypatch):
    values = iter((0, 1))
    monkeypatch.setattr(setup["worker"], "_population", lambda: next(values))
    with pytest.raises(kernel.KernelCustodyError, match="changed during cleanup observation"):
        setup["worker"].observe_cleanup()

