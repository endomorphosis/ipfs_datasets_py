"""Explicit simulated cgroup filesystem tests; never kernel qualification.

No real cgroup, process, native grant, Docker command or scheduler is created.
Every injected backend report must identify simulation, and admission is false.
"""
from __future__ import annotations

import copy
import errno
from pathlib import Path
import stat

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_kernel_custody as custody


MOUNT = Path("/sys/fs/cgroup")
ROOT = MOUNT / "unit"
WORKER = ROOT / "worker"
BOOT = "01234567-1234-1234-1234-0123456789ab"


class SimulatedCgroupFS:
    """Opaque held handles point at original nodes even after path replacement."""
    simulation = True

    def __init__(self):
        self.nodes, self.handles = {}, {}
        self.next_inode, self.next_fd = 10, 1000
        self.boot, self.clock = BOOT, 0.0
        self.kill_works = True
        self.writes = []
        self.processes = {100: dict(pid=100, birth=99, state="S", membership="/unit/worker")}
        self.mount_record = dict(path=str(MOUNT), root="/", mount_id=5,
                                 device="0:5", filesystem="cgroup2")
        for path in (Path("/"), Path("/sys"), Path("/sys/fs"), MOUNT, ROOT):
            self.add(path, directory=True)
        self.group(WORKER)

    def add(self, path, *, directory=False, text="", uid=1000, mode=None, links=1):
        self.next_inode += 1
        node = dict(path=str(path), text=text, cgroup2=True,
            info=dict(device=5, inode=self.next_inode, uid=uid,
                      mode=mode if mode is not None else
                          (stat.S_IFDIR | 0o755 if directory else stat.S_IFREG | 0o644),
                      links=links))
        self.nodes[str(path)] = node
        return node

    def group(self, path, *, processes="100", tasks=2, memory=256, peak=True):
        self.add(path, directory=True)
        controls = {"cgroup.type":"domain", "cgroup.events":f"populated {int(bool(processes))}\nfrozen 0",
            "cgroup.procs":processes, "memory.max":"1024", "memory.current":str(memory),
            "memory.swap.max":"0", "memory.oom.group":"1", "memory.events":
                "low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\noom_group_kill 0",
            "pids.max":"8", "pids.current":str(tasks), "cpu.max":"100000 100000",
            "cgroup.kill":""}
        if peak:
            controls["memory.peak"] = str(max(256, memory))
        for name, text in controls.items():
            self.add(path / name, text=text)

    def _handle(self, node):
        self.next_fd += 1
        self.handles[self.next_fd] = node
        return self.next_fd

    def open_dir(self, path):
        path = Path(path)
        for ancestor in (*reversed(path.parents), path):
            if str(ancestor) not in self.nodes:
                raise FileNotFoundError(errno.ENOENT, "simulated missing directory")
            if not stat.S_ISDIR(self.nodes[str(ancestor)]["info"]["mode"]):
                raise OSError(errno.ELOOP, "simulated symlink or non-directory")
        return self._handle(self.nodes[str(path)])

    def open_at(self, descriptor, name, *, writable=False):
        path = str(Path(self.handles[descriptor]["path"]) / name)
        if path not in self.nodes:
            raise FileNotFoundError(errno.ENOENT, "simulated missing control")
        node = self.nodes[path]
        if stat.S_ISLNK(node["info"]["mode"]):
            raise OSError(errno.ELOOP, "simulated symlink control")
        return self._handle(node)

    def identity(self, descriptor):
        return copy.deepcopy(self.handles[descriptor]["info"])

    def close(self, descriptor):
        del self.handles[descriptor]

    def read(self, descriptor, maximum):
        text = self.handles[descriptor]["text"]
        if len(text) > maximum:
            raise custody.KernelCustodyError("simulated counter byte bound exceeded")
        return text.strip()

    def write(self, descriptor, data):
        original = self.handles[descriptor]
        assert original["path"].endswith("/cgroup.kill")
        self.writes.append((original["info"]["inode"], data))
        if self.kill_works:
            group = Path(original["path"]).parent
            for path, node in self.nodes.items():
                current = Path(path)
                if current.parent == group or group in current.parent.parents:
                    if current.name == "cgroup.procs":
                        node["text"] = ""
                    elif current.name == "cgroup.events":
                        node["text"] = "populated 0\nfrozen 0"
                    elif current.name in {"pids.current", "memory.current"}:
                        node["text"] = "0"
            member_root = "/" + str(group.relative_to(MOUNT))
            for process in self.processes.values():
                if process["membership"] == member_root or process["membership"].startswith(member_root + "/"):
                    process["state"] = "Z"

    def list_dirs(self, descriptor):
        parent = Path(self.handles[descriptor]["path"])
        result = []
        for spelling, node in self.nodes.items():
            path = Path(spelling)
            if path.parent == parent and path != parent:
                if stat.S_ISLNK(node["info"]["mode"]):
                    raise custody.KernelCustodyError("simulated symlink in cgroup scope")
                if stat.S_ISDIR(node["info"]["mode"]):
                    result.append(path.name)
        return tuple(sorted(result))

    def assert_cgroup2(self, descriptor):
        if not self.handles[descriptor]["cgroup2"]:
            raise custody.KernelCustodyError("actual cgroup-v2 filesystem required")

    def boot_id(self):
        return self.boot

    def mount(self, path):
        return copy.deepcopy(self.mount_record)

    def process(self, pid):
        return copy.deepcopy(self.processes.get(pid))

    def monotonic(self):
        return self.clock

    def sleep(self, duration):
        self.clock += duration

    def text(self, name, value, *, group=WORKER):
        self.nodes[str(group / name)]["text"] = value


def bind(fs, **overrides):
    values = dict(expected_root=ROOT, expected_owner_uid=1000,
                  required_memory_max=1024, required_pids_max=8,
                  required_cpu_quota_us=100000, required_cpu_period_us=100000,
                  _backend=fs)
    values.update(overrides)
    return custody.bind_cgroup(WORKER, **values)


def test_simulation_observes_charged_memory_tasks_and_processes_separately():
    fs = SimulatedCgroupFS()
    with bind(fs) as scope:
        result = scope.observe()
        assert result["simulation"] is True
        assert result["admitted"] is result["native_admission"] is False
        assert result["memory_current_bytes"] == 256
        assert result["memory_peak_bytes"] == 256
        assert result["rss_bytes"] is None
        assert result["memory_scope"] == "hierarchical_kernel_charge_including_cache_and_tmpfs"
        assert result["task_count"] == 2
        assert result["process_count"] == 1
        assert result["process_ids"] == [100]
        assert result["hostile_same_uid_confinement"] is False
    assert fs.handles == {} and fs.writes == []


def test_simulation_missing_optional_peak_is_explicit_unknown():
    fs = SimulatedCgroupFS()
    del fs.nodes[str(WORKER / "memory.peak")]
    with bind(fs) as scope:
        assert scope.observe()["memory_peak_bytes"] is None


@pytest.mark.parametrize("name,value", [
    ("memory.max", "max"), ("memory.max", "1025"), ("memory.max", "nan"),
    ("memory.max", "-1"), ("memory.max", "01024"), ("pids.max", "max"),
    ("pids.max", "9"), ("cpu.max", "max 100000"), ("cpu.max", "100001 100000"),
    ("cpu.max", "100000 100001"), ("cpu.max", "100000"),
    ("memory.swap.max", "1"), ("memory.oom.group", "0"),
    ("cgroup.type", "domain threaded"), ("memory.current", "1025"),
    ("memory.peak", "128"), ("pids.current", "9"),
    ("cgroup.events", "frozen 0"), ("cgroup.events", "populated 2"),
    ("cgroup.events", "populated 1\npopulated 1"),
    ("memory.events", "oom 0"), ("memory.events", "oom 0\noom 1"),
    ("cgroup.procs", "100 100"), ("cgroup.procs", "0"),
    ("cgroup.procs", ""), ("pids.current", "0"),
])
def test_simulation_refuses_unsafe_or_unknown_controls_without_fd_leak(name, value):
    fs = SimulatedCgroupFS()
    fs.text(name, value)
    with pytest.raises(custody.KernelCustodyError):
        bind(fs)
    assert fs.handles == {} and fs.writes == []


@pytest.mark.parametrize("name", sorted(custody._REQUIRED))
def test_simulation_missing_required_control_refuses_binding(name):
    fs = SimulatedCgroupFS()
    del fs.nodes[str(WORKER / name)]
    with pytest.raises(custody.KernelCustodyError):
        bind(fs)
    assert not fs.handles


@pytest.mark.parametrize("change", ["uid", "world_write", "not_writable", "not_cgroup2", "symlink"])
def test_simulation_requires_private_real_cgroup_directory(change):
    fs = SimulatedCgroupFS()
    node = fs.nodes[str(WORKER)]
    if change == "uid":
        node["info"]["uid"] = 1001
    elif change == "world_write":
        node["info"]["mode"] = stat.S_IFDIR | 0o777
    elif change == "not_writable":
        node["info"]["mode"] = stat.S_IFDIR | 0o555
    elif change == "not_cgroup2":
        node["cgroup2"] = False
    else:
        node["info"]["mode"] = stat.S_IFLNK | 0o777
    with pytest.raises(custody.KernelCustodyError):
        bind(fs)
    assert not fs.handles


@pytest.mark.parametrize("root", [WORKER, WORKER / "nested", ROOT / "sibling", Path("relative")])
def test_simulation_refuses_equal_or_foreign_anchor(root):
    fs = SimulatedCgroupFS()
    with pytest.raises(custody.KernelCustodyError):
        bind(fs, expected_root=root)
    assert not fs.handles


def test_simulation_refuses_noncanonical_alias_paths():
    fs = SimulatedCgroupFS()
    with pytest.raises(custody.KernelCustodyError):
        custody.bind_cgroup(str(ROOT) + "/../unit/worker", expected_root=ROOT,
            expected_owner_uid=1000, required_memory_max=1024, required_pids_max=8,
            required_cpu_quota_us=100000, required_cpu_period_us=100000, _backend=fs)
    assert not fs.handles


@pytest.mark.parametrize("name", ["memory.current", "cgroup.kill"])
def test_simulation_control_aliases_are_rejected(name):
    fs = SimulatedCgroupFS()
    fs.nodes[str(WORKER / name)]["info"]["mode"] = stat.S_IFLNK | 0o777
    with pytest.raises(custody.KernelCustodyError):
        bind(fs, allow_drain=True)
    assert not fs.handles


@pytest.mark.parametrize("target", ["boot", "mount", "anchor", "scope", "control", "kill"])
def test_simulation_replaced_identity_prevents_observation_and_kill(target):
    fs = SimulatedCgroupFS()
    scope = bind(fs, allow_drain=True)
    try:
        if target == "boot":
            fs.boot = BOOT[:-1] + "c"
        elif target == "mount":
            fs.mount_record["mount_id"] += 1
        elif target in {"anchor", "scope"}:
            fs.add(ROOT if target == "anchor" else WORKER, directory=True)
        else:
            name = "memory.current" if target == "control" else "cgroup.kill"
            fs.add(WORKER / name, text="256" if target == "control" else "")
        with pytest.raises(custody.KernelCustodyError):
            scope.observe()
        with pytest.raises(custody.KernelCustodyError):
            scope.drain(1)
        assert fs.writes == []
    finally:
        scope.close()
    assert not fs.handles


def test_simulation_unrelated_parent_sibling_churn_does_not_invalidate_scope():
    fs = SimulatedCgroupFS()
    with bind(fs) as scope:
        fs.nodes[str(ROOT)]["info"]["links"] += 1
        fs.nodes[str(MOUNT)]["info"]["links"] += 1
        fs.group(ROOT / "foreign", processes="200", tasks=1)
        assert scope.observe()["process_ids"] == [100]


def test_simulation_recursive_inventory_is_frozen_and_hierarchical_memory_not_summed():
    fs = SimulatedCgroupFS()
    child = WORKER / "nested"
    fs.group(child, processes="200", tasks=1, memory=128)
    fs.text("pids.current", "3")
    with bind(fs) as scope:
        result = scope.observe()
        assert result["process_ids"] == [100, 200]
        assert result["process_count"] == 2 and result["task_count"] == 3
        assert result["memory_current_bytes"] == 256
        fs.group(WORKER / "unexpected", processes="300", tasks=1)
        with pytest.raises(custody.KernelCustodyError, match="no implicit adoption"):
            scope.observe()


def test_simulation_foreign_descendant_is_not_adopted():
    fs = SimulatedCgroupFS()
    fs.group(WORKER / "foreign", processes="200", tasks=1)
    fs.nodes[str(WORKER / "foreign")]["info"]["uid"] = 1001
    with pytest.raises(custody.KernelCustodyError):
        bind(fs)
    assert not fs.handles


def test_simulation_original_kill_fd_drains_descendants_but_never_sibling():
    fs = SimulatedCgroupFS()
    fs.group(ROOT / "sibling", processes="999", tasks=1)
    with bind(fs, allow_drain=True, expected_pid=100) as scope:
        held_kill_inode = fs.nodes[str(WORKER / "cgroup.kill")]["info"]["inode"]
        # New descendants are not admitted for productive observation; killing
        # the original hierarchical scope must still include them in cleanup.
        fs.group(WORKER / "unexpected", processes="200", tasks=1)
        receipt = scope.drain(timeout_seconds=1)
        assert receipt["simulation"] is True and receipt["drained"] is True
        assert receipt["populated"] is False and receipt["admitted"] is False
        assert fs.writes == [(held_kill_inode, b"1\n")]
        assert fs.nodes[str(WORKER / "unexpected/cgroup.events")]["text"].startswith("populated 0")
        assert fs.nodes[str(ROOT / "sibling/cgroup.procs")]["text"] == "999"


def test_simulation_observe_only_scope_cannot_drain():
    fs = SimulatedCgroupFS()
    with bind(fs) as scope:
        with pytest.raises(custody.KernelCustodyError, match="not authorized"):
            scope.drain(1)
        assert not fs.writes


def test_simulation_empty_scope_drain_needs_no_kill_write():
    fs = SimulatedCgroupFS()
    fs.text("cgroup.procs", "")
    fs.text("cgroup.events", "populated 0\nfrozen 0")
    fs.text("pids.current", "0")
    with bind(fs, allow_drain=True) as scope:
        assert scope.drain(1)["drained"] is True
        assert not fs.writes


def test_simulation_failed_kill_times_out_without_releasing_anything():
    fs = SimulatedCgroupFS()
    fs.kill_works = False
    with bind(fs, allow_drain=True) as scope:
        with pytest.raises(custody.KernelCustodyError, match="custody remains unresolved"):
            scope.drain(.1)
        assert fs.clock >= .1 and len(fs.writes) == 1
        assert scope.observe()["populated"] is True


def test_simulation_unknown_population_prevents_even_original_fd_kill():
    fs = SimulatedCgroupFS()
    with bind(fs, allow_drain=True) as scope:
        fs.text("cgroup.events", "populated unknown")
        with pytest.raises(custody.KernelCustodyError):
            scope.drain(1)
        assert not fs.writes


def test_simulation_limit_change_refuses_work_but_allows_exact_owned_cleanup():
    fs = SimulatedCgroupFS()
    with bind(fs, allow_drain=True) as scope:
        fs.text("memory.max", "max")
        with pytest.raises(custody.KernelCustodyError, match="finite"):
            scope.observe()
        assert scope.drain(1)["drained"] is True


@pytest.mark.parametrize("membership,birth,state", [
    ("/unit/sibling", 99, "S"), ("/unit/worker", 99, "Z")])
def test_simulation_expected_pid_must_initially_be_live_exact_member(membership, birth, state):
    fs = SimulatedCgroupFS()
    fs.processes[100].update(membership=membership, birth=birth, state=state)
    with pytest.raises(custody.KernelCustodyError):
        bind(fs, expected_pid=100)
    assert not fs.handles


def test_simulation_migrated_expected_process_prevents_drain_success_claim():
    fs = SimulatedCgroupFS()
    with bind(fs, allow_drain=True, expected_pid=100) as scope:
        fs.processes[100]["membership"] = "/unit/sibling"
        with pytest.raises(custody.KernelCustodyError, match="migrated"):
            scope.observe()
        with pytest.raises(custody.KernelCustodyError, match="survives"):
            scope.drain(1)


def test_simulation_reused_expected_pid_refuses_work_without_killing_replacement():
    fs = SimulatedCgroupFS()
    with bind(fs, allow_drain=True, expected_pid=100) as scope:
        fs.processes[100].update(birth=100, membership="/unit/sibling")
        with pytest.raises(custody.KernelCustodyError, match="reused"):
            scope.observe()
        assert scope.drain(1)["drained"] is True
        assert fs.processes[100]["state"] == "S"


def test_simulation_counter_read_is_bounded():
    fs = SimulatedCgroupFS()
    fs.text("memory.events", "x" * (custody.MAX_CONTROL_BYTES + 1))
    with pytest.raises(custody.KernelCustodyError, match="byte bound"):
        bind(fs)
    assert not fs.handles


def test_simulation_control_hardlink_is_rejected():
    fs = SimulatedCgroupFS()
    fs.nodes[str(WORKER / "memory.current")]["info"]["links"] = 2
    with pytest.raises(custody.KernelCustodyError, match="unaliased"):
        bind(fs)
    assert not fs.handles


@pytest.mark.parametrize("name,value", [
    ("required_memory_max", True), ("required_memory_max", 0),
    ("required_pids_max", -1), ("required_cpu_quota_us", float("nan")),
    ("required_cpu_period_us", 0), ("required_memory_max", 2**63),
    ("expected_owner_uid", True), ("allow_drain", 1),
])
def test_simulation_declared_envelope_requires_exact_bounded_integers(name, value):
    fs = SimulatedCgroupFS()
    with pytest.raises(custody.KernelCustodyError):
        bind(fs, **{name:value})
    assert not fs.handles


def test_simulation_closed_binding_cannot_observe_or_kill():
    fs = SimulatedCgroupFS()
    scope = bind(fs, allow_drain=True)
    scope.close()
    scope.close()
    with pytest.raises(custody.KernelCustodyError, match="closed"):
        scope.observe()
    with pytest.raises(custody.KernelCustodyError, match="closed"):
        scope.drain(1)
    assert not fs.handles and not fs.writes


@pytest.mark.parametrize("value", [0, -1, True, float("nan"), float("inf"), 61])
def test_simulation_drain_requires_finite_deadline(value):
    fs = SimulatedCgroupFS()
    with bind(fs, allow_drain=True) as scope:
        with pytest.raises(custody.KernelCustodyError):
            scope.drain(value)
        assert not fs.writes


def test_injected_backend_cannot_present_itself_as_real_kernel():
    fs = SimulatedCgroupFS()
    fs.simulation = False
    with pytest.raises(custody.KernelCustodyError, match="simulation"):
        bind(fs)
    assert not fs.handles


def simulated_stat(pid, state, birth):
    fields = [state] + ["0"] * 19
    fields[19] = str(birth)
    return f"{pid} (simulated worker) " + " ".join(fields)


def test_simulated_proc_reads_allow_scheduling_state_change(monkeypatch):
    backend = custody._LinuxBackend()
    stats = iter([simulated_stat(100, "R", 99), simulated_stat(100, "S", 99)])
    monkeypatch.setattr(backend, "_regular_read", lambda path, maximum:
        next(stats) if Path(path).name == "stat" else "0::/unit/worker")
    assert backend.process(100) == dict(pid=100, birth=99, state="S", membership="/unit/worker")


def test_simulated_proc_birth_change_is_not_a_scheduling_change(monkeypatch):
    backend = custody._LinuxBackend()
    stats = iter([simulated_stat(100, "R", 99), simulated_stat(100, "S", 100)])
    monkeypatch.setattr(backend, "_regular_read", lambda path, maximum:
        next(stats) if Path(path).name == "stat" else "0::/unit/worker")
    with pytest.raises(custody.KernelCustodyError, match="identity changed"):
        backend.process(100)


def test_simulated_mount_parser_binds_most_specific_real_cgroup2_mount(monkeypatch):
    backend = custody._LinuxBackend()
    raw = ("5 1 0:5 / /sys/fs/cgroup rw - cgroup2 cgroup rw\n"
           "6 1 0:6 / /tmp rw - tmpfs tmpfs rw\n")
    monkeypatch.setattr(backend, "_regular_read", lambda path, maximum:raw)
    result = backend.mount(WORKER)
    assert result == dict(path=str(MOUNT), root="/", mount_id=5, device="0:5", filesystem="cgroup2")


def test_simulated_mount_parser_refuses_non_cgroup2_source(monkeypatch):
    backend = custody._LinuxBackend()
    monkeypatch.setattr(backend, "_regular_read", lambda path, maximum:
        "5 1 0:5 / /sys/fs/cgroup rw - tmpfs tmpfs rw\n")
    with pytest.raises(custody.KernelCustodyError, match="mount not found"):
        backend.mount(WORKER)
