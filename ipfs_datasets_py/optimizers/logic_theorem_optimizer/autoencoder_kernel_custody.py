"""Held-descriptor observations of one explicitly selected cgroup-v2 scope.

This module never creates a cgroup, migrates a task, changes a limit, initializes
a scheduler, or grants admission. A caller owns those actions and must hold its
actual native resource grant. ``allow_drain=True`` authorizes killing only the
bound scope through its original held cgroup.kill descriptor. JSON is evidence,
not a capability that can reconstruct the binding. Same-UID cgroup writers are
not confined by this observer. Only actual lake build <Lib> admits Lean.
"""
from __future__ import annotations

import copy
import ctypes
import errno
import os
from pathlib import Path
import re
import stat
import time

SCHEMA = "autoencoder-held-cgroup-v2/v1"
CGROUP2_SUPER_MAGIC = 0x63677270
MAX_CONTROL_BYTES = 65536
MAX_GROUPS = 128
MAX_PROCESSES = 4096
MAX_DEPTH = 16
_CONTROLS = ("cgroup.type", "cgroup.events", "cgroup.procs", "memory.max",
    "memory.current", "memory.peak", "memory.swap.max", "memory.oom.group",
    "memory.events", "pids.max", "pids.current", "cpu.max")
_REQUIRED = frozenset(_CONTROLS) - {"memory.peak"}


class KernelCustodyError(RuntimeError):
    """Exact scope identity, controls or bounded observations are unavailable."""


def _need(condition, message):
    if not condition:
        raise KernelCustodyError(message)


def _integer(value, name, *, minimum=1):
    _need(type(value) is int and minimum <= value <= 2**63 - 1,
          "invalid " + name)
    return value


def _path(value):
    raw = os.fspath(value)
    _need(isinstance(raw, str) and raw.startswith("/") and len(raw) <= 4096
          and "\x00" not in raw, "absolute bounded cgroup path required")
    path = Path(raw)
    _need(str(path) == raw and all(part not in {".", ".."} for part in path.parts),
          "canonical cgroup path required")
    return path


def _identity(info):
    return {"device": info.st_dev, "inode": info.st_ino, "uid": info.st_uid,
            "mode": info.st_mode, "links": info.st_nlink}


def _directory_identity(info):
    # Directory nlink changes when sibling groups are created/deleted. It is
    # not part of mount/anchor identity; topology below the owned scope is
    # checked separately. Regular control files retain their one-link check.
    return {key: info[key] for key in ("device", "inode", "uid", "mode")}


def _number(raw, name, *, minimum=0):
    _need(bool(re.fullmatch(r"0|[1-9][0-9]*", raw)), "invalid finite " + name)
    return _integer(int(raw), name, minimum=minimum)


def _fields(raw, name):
    result = {}
    for line in raw.splitlines():
        parts = line.split()
        _need(len(parts) == 2 and re.fullmatch(r"[a-z_]+", parts[0])
              and parts[0] not in result, "invalid " + name)
        result[parts[0]] = _number(parts[1], name + "." + parts[0])
    _need(bool(result), "empty " + name)
    return result


class _LinuxBackend:
    simulation = False

    def open_dir(self, path):
        descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            for part in _path(path).parts[1:]:
                following = os.open(part, os.O_RDONLY | os.O_DIRECTORY
                    | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = following
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    def open_at(self, descriptor, name, *, writable=False):
        return os.open(name, (os.O_WRONLY if writable else os.O_RDONLY)
            | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=descriptor)

    def identity(self, descriptor):
        return _identity(os.fstat(descriptor))

    def close(self, descriptor):
        os.close(descriptor)

    def read(self, descriptor, maximum):
        os.lseek(descriptor, 0, os.SEEK_SET)
        data = os.read(descriptor, maximum + 1)
        _need(len(data) <= maximum, "cgroup counter byte bound exceeded")
        try:
            return data.decode("ascii").strip()
        except UnicodeError as error:
            raise KernelCustodyError("non-ASCII cgroup counter") from error

    def write(self, descriptor, data):
        _need(os.write(descriptor, data) == len(data), "partial cgroup kill write")

    def list_dirs(self, descriptor):
        names = os.listdir(descriptor)
        _need(len(names) <= 512, "cgroup directory entry bound exceeded")
        result = []
        for name in names:
            info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            _need(not stat.S_ISLNK(info.st_mode), "symlink in cgroup scope")
            if stat.S_ISDIR(info.st_mode):
                result.append(name)
        return tuple(sorted(result))

    def assert_cgroup2(self, descriptor):
        # Linux struct statfs is architecture dependent. A deliberately large
        # buffer avoids guessing its layout; its first member is a signed long.
        buffer = ctypes.create_string_buffer(512)
        libc = ctypes.CDLL(None, use_errno=True)
        call = libc.fstatfs
        call.argtypes = (ctypes.c_int, ctypes.c_void_p)
        call.restype = ctypes.c_int
        if call(descriptor, ctypes.byref(buffer)) != 0:
            raise OSError(ctypes.get_errno(), "fstatfs failed")
        _need(ctypes.c_long.from_buffer(buffer).value == CGROUP2_SUPER_MAGIC,
              "actual cgroup-v2 filesystem required")

    def _regular_read(self, path, maximum):
        parent = self.open_dir(Path(path).parent)
        try:
            descriptor = self.open_at(parent, Path(path).name)
            try:
                _need(stat.S_ISREG(self.identity(descriptor)["mode"]), "regular kernel metadata required")
                return self.read(descriptor, maximum)
            finally:
                self.close(descriptor)
        finally:
            self.close(parent)

    def boot_id(self):
        value = self._regular_read("/proc/sys/kernel/random/boot_id", 128)
        _need(bool(re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", value)),
              "kernel boot identity unavailable")
        return value

    def mount(self, path):
        raw = self._regular_read(f"/proc/{os.getpid()}/mountinfo", 512 * 1024)
        candidates = []
        for line in raw.splitlines():
            left, separator, right = line.partition(" - ")
            fields, kind = left.split(), right.split()
            if not separator or len(fields) < 6 or len(kind) < 3 or kind[0] != "cgroup2":
                continue
            # Escaped/spaced control paths need a separately reviewed profile.
            _need("\\" not in fields[3] + fields[4], "escaped cgroup mount path unsupported")
            mounted = _path(fields[4])
            if path == mounted or mounted in path.parents:
                candidates.append({"path": str(mounted), "root": str(_path(fields[3])),
                    "mount_id": _number(fields[0], "mount ID", minimum=1),
                    "device": fields[2], "filesystem": "cgroup2"})
        _need(bool(candidates), "cgroup-v2 mount not found")
        longest = max(len(item["path"]) for item in candidates)
        matches = [item for item in candidates if len(item["path"]) == longest]
        _need(len(matches) == 1, "ambiguous cgroup-v2 mount")
        return matches[0]

    def process(self, pid):
        def capture():
            raw = self._regular_read(Path("/proc") / str(pid) / "stat", 16384)
            closing = raw.rfind(")")
            fields = raw[closing + 2:].split()
            _need(closing > 0 and len(fields) >= 20 and raw.partition(" ")[0] == str(pid),
                  "invalid process stat")
            membership = self._regular_read(Path("/proc") / str(pid) / "cgroup", 16384)
            lines = membership.splitlines()
            _need(len(lines) == 1 and lines[0].startswith("0::"), "unified process cgroup required")
            return {"pid": pid, "birth": _number(fields[19], "process birth", minimum=1),
                    "state": fields[0], "membership": str(_path(lines[0][3:]))}
        try:
            before, after = capture(), capture()
            _need(all(before[key] == after[key] for key in ("pid", "birth", "membership")),
                  "process identity changed while reading")
            return after
        except OSError as error:
            if error.errno in {errno.ENOENT, errno.ESRCH}:
                return None
            raise

    def monotonic(self):
        return time.monotonic()

    def sleep(self, duration):
        time.sleep(duration)


class BoundCgroup:
    """One live held-FD scope; cannot be reconstructed from a receipt."""

    def __init__(self, path, expected_root, expected_owner_uid, limits, expected_pid,
                 allow_drain, backend):
        self._backend = backend
        self._descriptors = []
        self._groups = {}
        self._closed = False
        self._allow_drain = allow_drain
        self._path, self._root = _path(path), _path(expected_root)
        self._uid = _integer(expected_owner_uid, "owner UID", minimum=0)
        self._limits = limits
        self._expected_process = None
        _need(self._root in self._path.parents, "scope must be a strict descendant of expected root")
        try:
            self._boot = backend.boot_id()
            self._mount = backend.mount(self._path)
            mount_path = _path(self._mount["path"])
            _need(mount_path == self._root or mount_path in self._root.parents,
                  "expected root escaped cgroup mount")
            self._mount_fd = self._directory(mount_path)
            self._mount_identity = _directory_identity(backend.identity(self._mount_fd))
            self._root_fd = self._directory(self._root)
            self._root_identity = _directory_identity(backend.identity(self._root_fd))
            self._capture_groups(self._path, depth=0)
            self._leaf = self._groups[str(self._path)]
            self._kill_fd = None
            if allow_drain:
                self._kill_fd = self._control(self._leaf["fd"], "cgroup.kill", writable=True)
                self._kill_identity = backend.identity(self._kill_fd)
            if expected_pid is not None:
                _integer(expected_pid, "expected PID")
                process = backend.process(expected_pid)
                _need(process is not None and process["state"] != "Z"
                      and process["membership"] == self._membership(self._path),
                      "expected live process is outside exact cgroup")
                self._expected_process = process
            self.observe()
        except BaseException:
            self.close()
            raise

    def _directory(self, path):
        descriptor = self._backend.open_dir(path)
        self._descriptors.append(descriptor)
        self._backend.assert_cgroup2(descriptor)
        _need(stat.S_ISDIR(self._backend.identity(descriptor)["mode"]), "cgroup directory required")
        return descriptor

    def _control(self, directory, name, *, writable=False):
        descriptor = self._backend.open_at(directory, name, writable=writable)
        self._descriptors.append(descriptor)
        info = self._backend.identity(descriptor)
        _need(stat.S_ISREG(info["mode"]) and info["links"] == 1,
              "unaliased regular cgroup control required")
        return descriptor

    def _capture_groups(self, path, depth):
        _need(depth <= MAX_DEPTH and len(self._groups) < MAX_GROUPS, "cgroup tree bound exceeded")
        descriptor = self._directory(path)
        identity = _directory_identity(self._backend.identity(descriptor))
        _need(identity["uid"] == self._uid and stat.S_IMODE(identity["mode"]) & 0o200
              and not stat.S_IMODE(identity["mode"]) & 0o022,
              "private owner-writable cgroup directory required")
        controls, identities = {}, {}
        names = _CONTROLS if path == self._path else ("cgroup.type", "cgroup.events", "cgroup.procs")
        for name in names:
            try:
                controls[name] = self._control(descriptor, name)
                identities[name] = self._backend.identity(controls[name])
            except FileNotFoundError:
                _need(name == "memory.peak", "required cgroup control missing: " + name)
        children = self._backend.list_dirs(descriptor)
        self._groups[str(path)] = {"fd": descriptor, "identity": identity,
            "controls": controls, "control_identities": identities, "children": children}
        for child in children:
            _need(bool(re.fullmatch(r"[A-Za-z0-9_.:@+-]+", child)) and child not in {".", ".."},
                  "invalid child cgroup name")
            self._capture_groups(path / child, depth + 1)

    def _membership(self, path):
        return str(_path(self._mount["root"]) / path.relative_to(_path(self._mount["path"])))

    def _verify_directory(self, path, retained, identity):
        _need(_directory_identity(self._backend.identity(retained)) == identity,
              "held cgroup directory identity changed")
        current = self._backend.open_dir(path)
        try:
            _need(_directory_identity(self._backend.identity(current)) == identity,
                  "cgroup path identity changed")
            self._backend.assert_cgroup2(current)
        finally:
            self._backend.close(current)

    def _verify_control(self, group, name, descriptor, identity, *, writable=False):
        _need(self._backend.identity(descriptor) == identity, "held cgroup control identity changed")
        current = self._backend.open_at(group["fd"], name, writable=writable)
        try:
            _need(self._backend.identity(current) == identity, "cgroup control identity changed")
        finally:
            self._backend.close(current)

    def _verify(self, *, tree=True):
        _need(not self._closed, "cgroup binding is closed")
        backend = self._backend
        _need(backend.boot_id() == self._boot and backend.mount(self._path) == self._mount,
              "kernel boot or cgroup mount identity changed")
        self._verify_directory(_path(self._mount["path"]), self._mount_fd, self._mount_identity)
        self._verify_directory(self._root, self._root_fd, self._root_identity)
        groups = self._groups.items() if tree else [(str(self._path), self._leaf)]
        for path, group in groups:
            self._verify_directory(_path(path), group["fd"], group["identity"])
            if tree:
                _need(backend.list_dirs(group["fd"]) == group["children"],
                      "cgroup child population changed; no implicit adoption")
            for name, descriptor in group["controls"].items():
                self._verify_control(group, name, descriptor, group["control_identities"][name])
        if self._kill_fd is not None:
            self._verify_control(self._leaf, "cgroup.kill", self._kill_fd, self._kill_identity, writable=True)

    def _read(self, group, name):
        return self._backend.read(group["controls"][name], MAX_CONTROL_BYTES)

    def _population(self):
        events = _fields(self._read(self._leaf, "cgroup.events"), "cgroup.events")
        _need(events.get("populated") in {0, 1}, "unknown cgroup population")
        return events["populated"]

    def _check_expected_process(self, *, stopped=False):
        if self._expected_process is None:
            return
        expected = self._expected_process
        observed = self._backend.process(expected["pid"])
        original_alive = (observed is not None and observed["birth"] == expected["birth"]
                          and observed["state"] != "Z")
        if stopped:
            _need(not original_alive, "original bound process survives cgroup drain")
        elif observed is not None:
            _need(observed["birth"] == expected["birth"], "bound process PID was reused")
            if original_alive:
                _need(observed["membership"] == expected["membership"], "bound process migrated outside exact cgroup")

    def observe(self):
        """Read exact unchanged controls and aggregate kernel memory/tasks.

        Process IDs come from the frozen bounded subtree's cgroup.procs files.
        ``memory.current`` is hierarchical charged memory, never summed RSS.
        The task count includes threads and is distinct from process count.
        """
        try:
            self._verify()
            leaf = self._leaf
            for group in self._groups.values():
                _need(self._read(group, "cgroup.type") == "domain", "domain cgroup required")
            memory = _number(self._read(leaf, "memory.max"), "memory.max", minimum=1)
            pids = _number(self._read(leaf, "pids.max"), "pids.max", minimum=1)
            cpu = self._read(leaf, "cpu.max").split()
            _need(len(cpu) == 2, "invalid cpu.max")
            quota, period = (_number(value, "cpu.max", minimum=1) for value in cpu)
            _need((memory, pids, quota, period) == self._limits, "effective cgroup limits differ")
            _need(_number(self._read(leaf, "memory.swap.max"), "memory.swap.max") == 0,
                  "cgroup swap must be disabled")
            _need(self._read(leaf, "memory.oom.group") == "1", "group OOM termination must be enabled")
            current = _number(self._read(leaf, "memory.current"), "memory.current")
            tasks = _number(self._read(leaf, "pids.current"), "pids.current")
            _need(current <= memory and tasks <= pids, "cgroup usage exceeds declared limit")
            peak = (_number(self._read(leaf, "memory.peak"), "memory.peak")
                    if "memory.peak" in leaf["controls"] else None)
            _need(peak is None or peak >= current, "cgroup peak is below current usage")
            memory_events = _fields(self._read(leaf, "memory.events"), "memory.events")
            _need({"low", "high", "max", "oom", "oom_kill"}.issubset(memory_events),
                  "incomplete memory events")
            population = self._population()
            processes = set()
            for group in self._groups.values():
                for value in self._read(group, "cgroup.procs").split():
                    pid = _number(value, "cgroup process ID", minimum=1)
                    _need(pid <= 2**31 - 1 and pid not in processes
                          and len(processes) < MAX_PROCESSES, "invalid or moving process inventory")
                    processes.add(pid)
            _need(bool(processes) == bool(population) and len(processes) <= tasks,
                  "cgroup process/task/population observations disagree")
            self._check_expected_process()
            self._verify()
            _need(self._population() == population, "cgroup population changed during observation")
            return {"schema": SCHEMA, "simulation": self._backend.simulation,
                "path": str(self._path), "boot_id": self._boot, "mount": copy.deepcopy(self._mount),
                "expected_root": str(self._root), "root_identity": copy.deepcopy(self._root_identity),
                "mount_directory_identity": copy.deepcopy(self._mount_identity),
                "directory_identity": copy.deepcopy(leaf["identity"]),
                "expected_root": str(self._root),
                "root_identity": copy.deepcopy(self._root_identity),
                "control_identities": copy.deepcopy(leaf["control_identities"]),
                "group_tree": [{"path": path, "directory_identity": copy.deepcopy(group["identity"]),
                    "children": list(group["children"])} for path, group in self._groups.items()],
                "memory_current_bytes": current, "memory_peak_bytes": peak,
                "memory_max_bytes": memory, "memory_swap_max_bytes": 0,
                "memory_scope": "hierarchical_kernel_charge_including_cache_and_tmpfs",
                "rss_bytes": None, "task_count": tasks, "pids_max_tasks": pids,
                "process_count": len(processes), "process_ids": sorted(processes),
                "process_scope": "frozen_bounded_cgroup_subtree",
                "cpu_quota_us": quota, "cpu_period_us": period,
                "populated": bool(population), "memory_events": memory_events,
                "expected_process": copy.deepcopy(self._expected_process),
                "native_admission": False, "admitted": False,
                "hostile_same_uid_confinement": False}
        except OSError as error:
            raise KernelCustodyError("cgroup observation unavailable") from error

    def drain(self, timeout_seconds):
        """Kill the original held scope and require hierarchical populated=0.

        Limit-value changes do not redirect cleanup; identity changes or unknown
        population refuse it. Newly created descendants are killed by the same
        original hierarchical kernel scope, never adopted for productive work.
        """
        _need(type(timeout_seconds) in {int, float} and 0 < timeout_seconds <= 60,
              "finite cgroup drain deadline 0..60 seconds required")
        _need(self._allow_drain and self._kill_fd is not None, "cgroup drain was not authorized at binding")
        try:
            self._verify(tree=False)
            populated = self._population()
            started = self._backend.monotonic()
            deadline = started + timeout_seconds
            if populated:
                self._backend.write(self._kill_fd, b"1\n")
            while True:
                self._verify(tree=False)
                populated = self._population()
                if populated == 0:
                    self._check_expected_process(stopped=True)
                    return {"schema": SCHEMA, "simulation": self._backend.simulation,
                        "path": str(self._path), "directory_identity": copy.deepcopy(self._leaf["identity"]),
                        "populated": False, "drained": True,
                        "elapsed_seconds": self._backend.monotonic() - started,
                        "native_admission": False, "admitted": False}
                remaining = deadline - self._backend.monotonic()
                _need(remaining > 0, "cgroup drain deadline expired; custody remains unresolved")
                self._backend.sleep(min(.05, remaining))
        except OSError as error:
            raise KernelCustodyError("cgroup drain unavailable; custody remains unresolved") from error

    def close(self):
        """Close observations only; this never kills tasks or releases a lease."""
        if not self._closed:
            self._closed = True
            for descriptor in reversed(self._descriptors):
                self._backend.close(descriptor)
            self._descriptors.clear()

    def __enter__(self):
        _need(not self._closed, "cgroup binding is closed")
        return self

    def __exit__(self, *_):
        self.close()
        return False


def bind_cgroup(path, *, expected_root, expected_owner_uid, required_memory_max,
                required_pids_max, required_cpu_quota_us, required_cpu_period_us,
                expected_pid=None, allow_drain=False, _backend=None):
    """Bind an explicit private descendant without creating or admitting work.

    ``_backend`` is solely an explicit simulated-filesystem test seam. Its
    reports are always marked simulation and cannot constitute qualification.
    Root and child directories must already exist. Productive observation
    freezes their bounded topology; a new child requires a new explicit bind.
    """
    _need(type(allow_drain) is bool, "allow_drain must be a boolean")
    backend = _LinuxBackend() if _backend is None else _backend
    _need(_backend is None or getattr(backend, "simulation", None) is True,
          "injected backend must explicitly identify simulation")
    limits = tuple(_integer(value, name) for value, name in (
        (required_memory_max, "memory maximum"), (required_pids_max, "task maximum"),
        (required_cpu_quota_us, "CPU quota"), (required_cpu_period_us, "CPU period")))
    try:
        return BoundCgroup(path, expected_root, expected_owner_uid, limits,
                           expected_pid, allow_drain, backend)
    except OSError as error:
        raise KernelCustodyError("exact cgroup binding unavailable") from error


__all__ = ["bind_cgroup", "BoundCgroup", "KernelCustodyError"]
