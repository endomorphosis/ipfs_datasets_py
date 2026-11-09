"""Bind one exact container to held Linux execution scopes, without admission.

The caller owns bounded Docker inspection, actual native guards before/after,
source custody, process barriers, and draining/reaping. This module does not
create, start, kill, remove, acquire, or release anything. A JSON receipt cannot
reconstruct the held scope objects or this binding. The supported PID mapping
profile is a direct, same-UID dockerd socket peer in the scanner PID namespace;
proxies and a daemon in another PID namespace are refused, never guessed.
Identity labels are caller pins, not proof of OCI isolation, source capsule
authenticity, formal semantics, or actual native resource ownership.
"""
from __future__ import annotations

import copy
import hashlib
import os
from pathlib import Path
import re
import select
import socket
import stat
import struct
from types import ModuleType

from .autoencoder_controller_worker import observe_controller_worker
from .autoencoder_kernel_custody import BoundCgroup, KernelCustodyError


SCHEMA = "autoencoder-container-boundary/v1"
_HEX = re.compile(r"[0-9a-f]{64}")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_LABELS = ("ipfs_datasets.source_sha256", "ipfs_datasets.request_sha256",
           "ipfs_datasets.nonce")
_TOKEN = object()


def _need(condition, message):
    if not condition:
        raise KernelCustodyError(message)


def _hash_regular_fd(descriptor, *, maximum_bytes):
    before = os.fstat(descriptor)
    _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
          and 0 < before.st_size <= maximum_bytes,
          "bounded single-link regular file required for source/executable digest")
    digest = hashlib.sha256()
    count = 0
    while True:
        block = os.read(descriptor, min(1024 * 1024, maximum_bytes + 1 - count))
        if not block:
            break
        count += len(block)
        _need(count <= maximum_bytes, "source/executable digest byte bound exceeded")
        digest.update(block)
    after = os.fstat(descriptor)
    _need(_identity(before) == _identity(after) and after.st_nlink == 1
          and count == before.st_size, "source/executable changed while hashed")
    return digest.hexdigest(), _identity(after)


def _open_unaliased_source(path):
    """Walk every component with held directory FDs and O_NOFOLLOW."""
    directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for component in path.parts[1:-1]:
            following = os.open(component, os.O_RDONLY | os.O_DIRECTORY
                                | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = following
        return os.open(path.name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
                       | os.O_NONBLOCK, dir_fd=directory)
    finally:
        os.close(directory)


def _source_sha256(path):
    descriptor = _open_unaliased_source(path)
    try:
        digest, identity = _hash_regular_fd(descriptor, maximum_bytes=2 * 1024 * 1024)
        confirmed = _open_unaliased_source(path)
        try:
            _need(_identity(os.fstat(confirmed)) == identity
                  and os.fstat(confirmed).st_nlink == 1,
                  "process-security source path changed while hashed")
        finally:
            os.close(confirmed)
        return digest
    finally:
        os.close(descriptor)


def _executable_sha256(path):
    # /proc/<pid>/exe is deliberately a kernel magic link, unlike source paths.
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
    try:
        return _hash_regular_fd(descriptor, maximum_bytes=256 * 1024 * 1024)[0]
    finally:
        os.close(descriptor)


def _identity(value):
    return (value.st_dev, value.st_ino, value.st_uid, value.st_mode,
            value.st_size, value.st_mtime_ns, value.st_ctime_ns)


class ProcessSecurityAdapter:
    """Existing Linux capture/quiescence helpers from one exact pinned source.

    Supply the actual imported process_security module, its absolute source
    path and SHA256. No bare import or provider-specific cleanup is performed.
    The private backend seam is only for explicit simulated tests.
    """

    def __init__(self, module, *, expected_path, expected_sha256, _backend=None):
        _need(_backend is None or getattr(_backend, "simulation", None) is True,
              "process-security test backend must explicitly identify simulation")
        self.simulation = _backend is not None
        self._backend, self._module = _backend, module
        raw_path = os.fspath(expected_path)
        self._path, self._sha = Path(raw_path), expected_sha256
        _need(self._path.is_absolute() and not raw_path.startswith("//")
              and raw_path == os.path.normpath(raw_path)
              and _HEX.fullmatch(str(self._sha)),
              "exact process-security source path and SHA256 required")
        self._verify()

    def _verify(self):
        if self.simulation:
            return
        _need(type(self._module) is ModuleType, "actual process-security module required")
        _need(getattr(self._module, "__file__", None) == str(self._path),
              "process-security source origin or SHA256 differs")
        try:
            source_sha = _source_sha256(self._path)
        except OSError as error:
            raise KernelCustodyError("unaliased process-security source unavailable") from error
        _need(source_sha == self._sha, "process-security source origin or SHA256 differs")
        for name in ("capture_linux_process_scope", "validate_linux_process_scope",
                     "linux_process_scope_quiescent"):
            function = getattr(self._module, name, None)
            _need(callable(function) and hasattr(function, "__code__")
                  and function.__code__.co_filename == str(self._path)
                  and function.__module__ == self._module.__name__,
                  "process-security function source differs")

    def _call(self, name, *args):
        self._verify()
        target = self._backend if self.simulation else self._module
        result = getattr(target, name)(*args)
        self._verify()
        return result

    def capture(self, pid):
        return self._call("validate_linux_process_scope",
                          self._call("capture_linux_process_scope", pid))

    def quiescent(self, scope):
        return self._call("linux_process_scope_quiescent", copy.deepcopy(scope)) is True


def _require_idle_connection(connection):
    # A positive Python socket timeout triggers an internal blocking poll
    # even with MSG_DONTWAIT. Check readiness first so a healthy idle
    # dedicated connection never enters that poll. There are no other
    # readers on this attestation-only channel.
    pending = None
    if select.select((connection,), (), (), 0)[0]:
        try:
            pending = connection.recv(1, socket.MSG_PEEK | socket.MSG_DONTWAIT)
        except BlockingIOError:
            pending = None
    _need(pending is None,
          "dedicated daemon attestation socket closed or has unexpected pending data")


class _LinuxPeerBackend:
    simulation = False

    def __init__(self):
        self._executable_identity = self._executable_sha = None

    def peer(self, connection, path):
        _need(type(connection) is socket.socket and connection.fileno() >= 0
              and connection.family == socket.AF_UNIX
              and connection.type & socket.SOCK_STREAM == socket.SOCK_STREAM,
              "live connected AF_UNIX stream socket required")
        _need(connection.getpeername() == str(path), "daemon socket path differs")
        _require_idle_connection(connection)
        before = path.lstat()
        _need(stat.S_ISSOCK(before.st_mode) and before.st_uid == os.geteuid()
              and not before.st_mode & stat.S_IWOTH,
              "daemon socket must be same-UID and not world writable")
        pid, uid, gid = struct.unpack("3i", connection.getsockopt(
            socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
        _need(pid > 0 and uid == os.geteuid(), "daemon socket peer owner differs")
        proc = Path("/proc") / str(pid)
        raw = (proc / "stat").read_text(encoding="ascii")
        _need(0 < len(raw) <= 16384 and raw.startswith(str(pid) + " ("),
              "daemon peer stat is invalid")
        fields = raw[raw.rfind(")") + 2:].split()
        _need(len(fields) >= 20 and fields[0] != "Z", "daemon peer is not live")
        birth = int(fields[19])
        executable = os.readlink(proc / "exe")
        _need(Path(executable).is_absolute() and not executable.endswith(" (deleted)"),
              "daemon executable is unavailable")
        exe = (proc / "exe").stat()
        _need(stat.S_ISREG(exe.st_mode) and exe.st_uid == 0
              and not exe.st_mode & (stat.S_IWGRP | stat.S_IWOTH),
              "direct daemon executable must be root-owned and immutable to peers")
        namespace = (proc / "ns/pid").stat()
        scanner = Path("/proc/self/ns/pid").stat()
        exe_identity = _identity(exe)
        executable_sha = (self._executable_sha
            if exe_identity == self._executable_identity else _executable_sha256(proc / "exe"))
        result = dict(pid=pid, uid=uid, gid=gid, start_time_ticks=birth,
            socket_identity=_identity(before), executable=executable,
            executable_identity=exe_identity, executable_sha256=executable_sha,
            pid_namespace=(namespace.st_dev, namespace.st_ino),
            scanner_pid_namespace=(scanner.st_dev, scanner.st_ino))
        after = (proc / "stat").read_text(encoding="ascii")
        _need(int(after[after.rfind(")") + 2:].split()[19]) == birth
              and _identity((proc / "exe").stat()) == result["executable_identity"]
              and _identity(path.lstat()) == result["socket_identity"]
              and os.readlink(proc / "exe") == executable
              and ((proc / "ns/pid").stat().st_dev,
                   (proc / "ns/pid").stat().st_ino) == result["pid_namespace"],
              "daemon peer changed while captured")
        # Hash a root-owned, non-writable executable once. Every observation
        # still verifies live /proc/exe identity including size, mtime and ctime.
        self._executable_identity, self._executable_sha = exe_identity, executable_sha
        return result


class DirectDockerPeer:
    """A live direct daemon socket, not a serializable daemon PID receipt."""

    def __init__(self, connection, *, socket_path, expected_pid,
                 expected_start_time_ticks, expected_executable,
                 expected_executable_sha256, _backend=None):
        _need(_backend is None or getattr(_backend, "simulation", None) is True,
              "daemon test backend must explicitly identify simulation")
        self.simulation = _backend is not None
        self._backend = _LinuxPeerBackend() if _backend is None else _backend
        self._connection, self._path = connection, Path(socket_path)
        self._executable = Path(expected_executable)
        self._sha = expected_executable_sha256
        _need(self._path.is_absolute() and self._executable.is_absolute()
              and self._executable.name == "dockerd"
              and _HEX.fullmatch(str(self._sha))
              and type(expected_pid) is int and expected_pid > 0
              and type(expected_start_time_ticks) is int and expected_start_time_ticks > 0,
              "exact direct dockerd socket, PID, birth and executable pins required")
        self._pid, self._birth = expected_pid, expected_start_time_ticks
        self._original = self._capture()

    def _capture(self):
        try:
            observed = self._backend.peer(self._connection, self._path)
            _need(observed["pid"] == self._pid
                  and observed["start_time_ticks"] == self._birth
                  and observed["executable"] == str(self._executable)
                  and observed["executable_sha256"] == self._sha,
                  "direct daemon peer PID, birth or executable differs")
            _need(observed["pid_namespace"] == observed["scanner_pid_namespace"],
                  "daemon PID namespace differs; Docker State.Pid is not a host mapping")
            return observed
        except (OSError, ValueError, KeyError, IndexError) as error:
            raise KernelCustodyError("direct daemon peer observation unavailable") from error

    def observe(self):
        current = self._capture()
        _need(current == self._original, "original direct daemon socket peer changed")
        return copy.deepcopy(current)


def _inspection(inspect, expected):
    raw = inspect(expected["container_id"])
    _need(isinstance(raw, list) and len(raw) == 1 and isinstance(raw[0], dict),
          "one exact bounded container inspection required")
    value = raw[0]
    config, state, host = value.get("Config"), value.get("State"), value.get("HostConfig")
    _need(isinstance(config, dict) and isinstance(state, dict) and isinstance(host, dict),
          "container config, state or host configuration is missing")
    labels = config.get("Labels")
    _need(isinstance(labels, dict) and all(labels.get(key) == expected[key] for key in _LABELS)
          and value.get("Id") == expected["container_id"]
          and value.get("Name") == "/" + expected["container_name"]
          and value.get("Image") == expected["image_id"],
          "container CID, name, image or source/request/nonce labels differ")
    _need(host.get("PidMode") in {"", "private"}, "container PID namespace must be private")
    _need(type(state.get("Pid")) is int and state["Pid"] > 0
          and state.get("Running") is True
          and state.get("Restarting") is False and state.get("Dead") is False
          and state.get("Status") in {"running", "paused"}
          and type(state.get("Paused")) is bool
          and state["Paused"] is (state["Status"] == "paused")
          and isinstance(state.get("StartedAt"), str)
          and 0 < len(state["StartedAt"]) <= 128
          and not state["StartedAt"].startswith("0001-"),
          "live executed container state required; zero PID cannot create a binding")
    return dict(pid=state["Pid"], status=state["Status"], paused=state["Paused"],
                started_at=state["StartedAt"], pid_mode=host["PidMode"])


def _matches_worker(scope, worker, observation, peer):
    _need(scope["boot_id"] == observation["boot_id"], "container boot differs from worker")
    _need((scope["pid_namespace_device"], scope["pid_namespace_inode"])
          != peer["scanner_pid_namespace"], "container is in host PID namespace")
    mount = observation["mount_directory_identity"]
    _need((scope["cgroup_mount_device"], scope["cgroup_mount_inode"])
          == (mount["device"], mount["inode"]), "container cgroup mount differs")
    member = "/" + scope["cgroup_relative_path"]
    matching = [group for path, group in worker._groups.items()
                if worker._membership(Path(path)) == member]
    _need(len(matching) == 1, "container cgroup is not in original held worker subtree")
    directory, events = matching[0]["identity"], matching[0]["control_identities"]["cgroup.events"]
    _need((scope["cgroup_directory_device"], scope["cgroup_directory_inode"])
          == (directory["device"], directory["inode"])
          and (scope["cgroup_events_device"], scope["cgroup_events_inode"])
          == (events["device"], events["inode"]), "container cgroup inode or events identity differs")
    process = worker._backend.process(scope["pid"])
    _need(process is not None and process["state"] != "Z"
          and process["birth"] == scope["start_time_ticks"]
          and process["membership"] == member
          and scope["pid"] in observation["process_ids"],
          "container init disappeared, changed birth or moved outside held worker")


class BoundContainerExecution:
    """Retained live bindings; no JSON constructor, destructor or release API.

    The durable held worker must remain addressable until quiescence is
    checked. A generated container descendant may already have been removed
    after init exit; the original namespace helper must still establish its
    exact process/namespace quiescence. Do not use Docker auto-remove. Owner
    death does not prevent cleanup observations; release is the guardian's duty.
    """

    def __init__(self, token, controller, worker, adapter, scope, receipt):
        _need(token is _TOKEN, "use live container attestation, never a JSON receipt")
        self._controller, self._worker = controller, worker
        self._adapter, self._scope = adapter, copy.deepcopy(scope)
        self._receipt = copy.deepcopy(receipt)

    def receipt(self):
        """Return historical evidence only, never a fresh admission decision."""
        return copy.deepcopy(self._receipt)

    def quiescent(self):
        """Require both original PID namespace/container cgroup and worker empty.

        No native release occurs even on True. Unknown identities, disappeared
        worker bindings, a surviving namespace member or worker population fail
        closed. Actual native and source guards are caller responsibilities.
        """
        try:
            controller = self._controller.observe_cleanup()
            worker = self._worker.observe_cleanup()
            original = self._receipt["worker"]
            _need(worker["directory_identity"] == original["directory_identity"]
                  and worker["root_identity"] == controller["directory_identity"]
                  and worker["expected_root"] == controller["path"]
                  and worker["boot_id"] == controller["boot_id"]
                  and worker["mount"] == controller["mount"], "held scope ancestry changed")
            if worker["populated"] or not self._adapter.quiescent(self._scope):
                return False
            worker = self._worker.observe_cleanup()
            self._controller.observe_cleanup()
            if worker["populated"] or not self._adapter.quiescent(self._scope):
                return False
            # A helper observation can span another process appearing in the
            # wider worker. Finish with the original held worker, not cached
            # population from before that helper call. This remains sequential
            # evidence, never an atomic exclusion or an implicit native release.
            worker = self._worker.observe_cleanup()
            self._controller.observe_cleanup()
            return worker["populated"] is False
        except Exception:
            return False


def attest_container_execution(controller_scope, worker_scope, *,
        container_id, container_name, image_id, source_sha256, request_sha256, nonce,
        docker_inspect, process_security, daemon_peer, owner_pid,
        native_memory_bytes, native_child_process_slots):
    """Inspect/capture/inspect/recapture one exact paused or running container.

    Native admission must already exist and be guarded by the caller before
    and after this call. Inspect must be a bounded read-only exact-CID command
    on the same daemon as daemon_peer. Build both frozen cgroup bindings after
    inert container topology exists, before releasing any productive barrier.
    This function does not authenticate caller-supplied native budget numbers.
    """
    _need(type(controller_scope) is BoundCgroup and type(worker_scope) is BoundCgroup,
          "actual held controller and worker required")
    _need(type(process_security) is ProcessSecurityAdapter and type(daemon_peer) is DirectDockerPeer,
          "live pinned process-security adapter and direct daemon socket required")
    _need(callable(docker_inspect) and _HEX.fullmatch(str(container_id))
          and _NAME.fullmatch(str(container_name))
          and re.fullmatch(r"sha256:[0-9a-f]{64}", str(image_id))
          and all(_HEX.fullmatch(str(value)) for value in (source_sha256, request_sha256, nonce)),
          "exact container and source/request/nonce pins required")
    expected = dict(container_id=container_id, container_name=container_name, image_id=image_id,
                    **dict(zip(_LABELS, (source_sha256, request_sha256, nonce))))
    limits = dict(owner_pid=owner_pid, native_memory_bytes=native_memory_bytes,
                  native_child_process_slots=native_child_process_slots)
    before = observe_controller_worker(controller_scope, worker_scope, **limits)
    _need(before["simulation"] is process_security.simulation
          and before["simulation"] is daemon_peer.simulation,
          "simulated adapters cannot be mixed with real held scopes")
    peer = daemon_peer.observe()
    inspected = _inspection(docker_inspect, expected)
    scope = process_security.capture(inspected["pid"])
    _need(scope["pid"] == inspected["pid"], "captured PID differs from exact inspected init")
    confirmed = _inspection(docker_inspect, expected)
    _need(confirmed == inspected, "container changed during process-scope capture")
    _need(process_security.capture(inspected["pid"]) == scope,
          "container init birth, namespace or cgroup changed during confirmation")
    _need(daemon_peer.observe() == peer, "direct daemon peer changed during attestation")
    after = observe_controller_worker(controller_scope, worker_scope, **limits)
    _matches_worker(scope, worker_scope, after["worker"], peer)
    receipt = dict(schema=SCHEMA, **expected, execution=inspected, kernel_scope=scope,
        daemon_peer=peer, worker=after["worker"], controller=after["controller"],
        simulation=after["simulation"], observation_only=True, native_admission=False,
        admitted=False, Lean_admitted=False, atomic_observation=False,
        host_pid_mapping="direct_dockerd_same_scanner_pid_namespace",
        native_ownership_authenticated=False, container_semantic_qualification=False)
    return BoundContainerExecution(_TOKEN, controller_scope, worker_scope,
                                   process_security, scope, receipt)


__all__ = ["ProcessSecurityAdapter", "DirectDockerPeer", "BoundContainerExecution",
           "attest_container_execution", "SCHEMA"]
