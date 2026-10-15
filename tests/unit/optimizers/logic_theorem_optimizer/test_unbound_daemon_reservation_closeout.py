"""Private control-protocol cases; these tests grant no storage or Lean admission.

Every file and ledger below lives under pytest's private directory. Runtime
injection is explicit; the production CLI does not select this test runtime.
"""
from contextlib import contextmanager
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest


SELECTED = ("6eb0cccf427e4ac79e76f15b888313e0", "36b6e6ce4be8463fae8cadaa828a4177")
OWNERS = (1020862, 1070490)
PROTECTED = "19253d4d7e1c4ba78d587c370e532715"
PRIVATE_POLICY = {"private_native_test_policy": 1}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n")
    return {"path": str(path), "sha256": sha(path.read_bytes())}


@pytest.fixture(scope="module")
def operator():
    # Direct loading also keeps these tests usable without scripts being a package.
    tree = Path(__file__).resolve().parents[4]
    path = tree / "scripts/ops/logic/reconcile_unbound_daemon_reservations.py"
    name = "_test_unbound_daemon_reservation_operator"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class PrivateLedger:
    def __init__(self, path, roots):
        self.path = path
        self.roots = tuple(Path(row["path"]) for row in roots)
        self.root_identities = copy.deepcopy(roots)
        self.writes = []
        self.locked = False
        self.before_write = None
        self.after_write = None

    @contextmanager
    def _locked(self):
        assert not self.locked
        self.locked = True
        try:
            yield
        finally:
            self.locked = False

    def _read(self):
        assert self.locked
        return json.loads(self.path.read_bytes())

    def _write(self, value):
        assert self.locked
        if self.before_write is not None:
            self.before_write()
        self.writes.append(copy.deepcopy(value))
        write_json(self.path, value)
        if self.after_write is not None:
            self.after_write()


class ExplicitTestRuntime:
    """Narrow, injected host observations, never a monkeypatched host scheduler."""
    inventory_timeout_seconds = 25.0
    lock_hold_seconds = 40.0

    def __init__(self, tree, ledger, operator):
        self.workspace_tree = tree
        self.control_lease_id = "a" * 32
        self.ledger = ledger
        self.operator = operator
        self.monotonic = 100.0
        self.wall = 2000.0
        self.processes = {1117622: {"pid": 1117622, "parent_pid": 1, "birth": "1234567", "state": "S"}}
        self.inventory = {"apparent_bytes": 700_000_123, "entry_count": 9, "symlink_count": 1, "special_file_count": 0}
        self.inventory_calls = []
        self.inventory_error = None
        self.inventory_error_on_call = None
        self.inventory_delay = 0.0
        self.source_error = None
        self.native_error = None
        self.ancestors = {555: {"pid": 555, "birth": "777", "state": "S", "parent_pid": 1}}
        self.current_boot_id = "b" * 32
        self.native_state = {"config": copy.deepcopy(PRIVATE_POLICY), "waiters": {}, "leases": {
            self.control_lease_id: {"owner_pid": 555, "owner_birth_marker": "777", "owner_boot_id": self.current_boot_id,
                "lane": "validation", "parent_lease_id": None, "expires_at": 2100.0,
                "cpu_slots": 1, "memory_mb": 1536, "child_process_slots": 4,
                "cancelled": False, "release_requested": False},
        }}

    def guard_sources(self, evidence):
        if self.source_error is not None:
            raise self.source_error
        # Exercise the production binding/hash checks over private regular files.
        return self.operator.Runtime.guard_sources(self, evidence)

    def process(self, pid):
        return copy.deepcopy(self.processes.get(pid))

    def helper(self, evidence):
        return self.ledger

    def native_check(self, evidence):
        if self.native_error is not None:
            raise self.native_error
        # Run the production checker against the explicit private snapshot.
        return self.operator.validate_native_snapshot(evidence, self.native_state,
            control_lease_id=self.control_lease_id, ancestors=self.ancestors,
            current_boot_id=self.current_boot_id, now=self.wall)

    def census(self, evidence, timeout_seconds):
        self.inventory_calls.append(timeout_seconds)
        self.monotonic += self.inventory_delay
        if self.inventory_error is not None and (self.inventory_error_on_call is None or len(self.inventory_calls) == self.inventory_error_on_call):
            raise self.inventory_error
        return copy.deepcopy(self.inventory)

    def filesystem_free(self, root):
        return 200_000_000_000

    def clock(self):
        return self.monotonic

    def wall_time(self):
        return self.wall

    def sleep(self, seconds):
        self.monotonic += seconds


@pytest.fixture
def case(tmp_path, operator):
    policy = operator.digest(PRIVATE_POLICY)
    tree = tmp_path / "source-tree"
    tree.mkdir()
    source_pins = {}
    for relative in [
        "scripts/ops/legal_ir/run_legacy_span_cuda.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legacy_span_campaign_resources.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/resource_scheduler.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/existing_resource_scheduler.py",
    ]:
        path = tree / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# private source fixture\n")
        source_pins[str(path)] = sha(path.read_bytes())
    roots = []
    for name in ["test-logs", "todo-queues", "evidence", "temporary"]:
        path = tree / "workspace" / name
        path.mkdir(parents=True)
        stat = path.stat()
        roots.append({"path": str(path), "device": stat.st_dev, "inode": stat.st_ino})
    rows = {}
    for index, (reservation_id, owner_pid) in enumerate(zip(SELECTED, OWNERS)):
        rows[reservation_id] = {
            "artifacts_durable_asserted": False, "attempt_directory": None,
            "child": None, "child_process_slots": 5, "cpu_slots": 3,
            "created_at": 1000.0 + index * 100, "external_charges": {},
            "last_usage": {"scope": "named_roots_only_apparent_bytes", "inventory": {"apparent_bytes": 900_000_123, "entry_count": 15, "symlink_count": 0, "special_file_count": 0}},
            "memory_mb": 8192, "owner_pid": owner_pid, "prior_children": [],
            "reservation_id": reservation_id, "retention_reason": "scheduler_admission_failed",
            "scheduler_lane": "hammer_lean", "status": "retained", "storage_bytes": 1_000_000_000,
            "workload": "canonical_trainer",
        }
    foreign = {"reservation_id": PROTECTED, "owner_pid": 1117622, "status": "active", "storage_bytes": 123456789,
        "attempt_directory": {"path": str(Path(roots[0]["path"]) / "active-attempt"), "device": roots[0]["device"], "inode": 987},
        "opaque_foreign_body": {"must": ["remain", "unchanged"]}}
    rows[PROTECTED] = foreign
    ledger_path = Path(roots[0]["path"]) / "disk-reservations.json"
    write_json(ledger_path, {"schema": "daemon-resource-reservations-v1", "roots": roots, "limit_bytes": 160_000_000_000, "reservations": rows})
    binding = write_json(tmp_path / "source-binding.json", {"schema": "frozen-cuda-pressure-regression-inputs/v1", "source_sha256": source_pins})
    evidence = {
        "schema": "trusted-unbound-admission-closeout-evidence/v1", "workspace_tree": str(tree),
        "ledger_path": str(ledger_path), "roots": roots, "limit_bytes": 160_000_000_000,
        "scheduler": {"state_path": str(tmp_path / "native-state.json"), "policy_sha256": policy},
        "protected_active_owner": {"reservation_id": PROTECTED, "pid": 1117622, "birth": "1234567"},
        "historical_source_binding": binding, "source_pins": source_pins, "selected": [],
    }
    for index, (reservation_id, owner_pid) in enumerate(zip(SELECTED, OWNERS)):
        created = rows[reservation_id]["created_at"]
        invocation = str(index + 1) * 32
        boot = "b" * 32
        command = "/usr/bin/python3 -B " + str(tree / "scripts/ops/legal_ir/run_legacy_span_cuda.py") + " --batch-size 8"
        base = {"_PID": str(owner_pid), "_SYSTEMD_INVOCATION_ID": invocation, "_BOOT_ID": boot,
            "_UID": str(os.geteuid()), "_SYSTEMD_USER_UNIT": "legacy-cuda-span-census.service", "_CMDLINE": command,
            "__REALTIME_TIMESTAMP": str(int((created + 0.5) * 1_000_000))}
        messages = [
            "Traceback (most recent call last):",
            f'  File "{tree}/scripts/ops/legal_ir/run_legacy_span_cuda.py", line 965, in <module>',
            "    raise SystemExit(main())", "                     ^^^^^^",
            f'  File "{tree}/scripts/ops/legal_ir/run_legacy_span_cuda.py", line 886, in main',
            "    resource.open()",
            f'  File "{tree}/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legacy_span_campaign_resources.py", line 266, in open',
            "    self.reservation.__enter__()",
            f'  File "{tree}/ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py", line 457, in __enter__',
            "    self._lease = self._acquire_native_lease(scheduler, scheduler_lane)",
            "                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^",
            f'  File "{tree}/ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py", line 471, in _acquire_native_lease',
            "    return (scheduler if scheduler is not None else get_global_resource_scheduler()).acquire(",
            "           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^",
            f'  File "{tree}/ipfs_datasets_py/optimizers/logic_theorem_optimizer/resource_scheduler.py", line 2137, in acquire',
            "    raise error",
            "ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler.LeaseTimeoutError: timed out waiting for a resource lease",
        ]
        journal_path = tmp_path / f"journal-{owner_pid}.jsonl"
        journal_path.write_text("".join(json.dumps(dict(base, MESSAGE=message)) + "\n" for message in messages))
        refusal = {"schema": "proof-resource-admission-refusal@1", "historical": True, "gate": "envelope", "lane": "hammer_lean",
            "parent_lease_id": None, "request_id": "daemon:" + reservation_id, "reason": "proof_pid_headroom" if index == 0 else "proof_memory_headroom",
            "decision_cycle_at": created + 0.1, "demand": {"additional_memory_mb": 8192, "additional_process_slots": 5}, "waiter_id": "c" * 32}
        refused = write_json(tmp_path / f"refusal-{owner_pid}.json", {"refusal": refusal})
        refused["keys"] = ["refusal"]
        execution = write_json(tmp_path / f"execution-{owner_pid}.json", {
            "schema": "legacy-cuda-single-resume-after-headroom-fix/v1", "started_at_unix": created - 10,
            "returncode": 0, "service_before": {"MainPID": "0", "ActiveState": "failed"},
            "service_after": {"MainPID": str(owner_pid), "ActiveState": "active", "NRestarts": "0"},
            "storage_limit_bytes": 160_000_000_000, "attempt_storage_bytes": 1_000_000_000,
            "policy_sha256": policy, "automatic_restart_enabled": False,
        })
        evidence["selected"].append({"reservation_id": reservation_id, "owner_pid": owner_pid,
            "expected_record_sha256": operator.digest(rows[reservation_id]), "invocation_id": invocation, "boot_id": boot,
            "journal": {"path": str(journal_path), "sha256": sha(journal_path.read_bytes())}, "refusal": refused, "execution_receipt": execution})
    evidence_path = tmp_path / "closeout-evidence.json"
    write_json(evidence_path, evidence)
    runtime = ExplicitTestRuntime(tree, PrivateLedger(ledger_path, roots), operator)
    return {"operator": operator, "evidence": evidence, "evidence_path": evidence_path, "runtime": runtime,
        "initial": copy.deepcopy(json.loads(ledger_path.read_bytes())), "tmp_path": tmp_path}


def plan(case):
    write_json(case["evidence_path"], case["evidence"])
    return case["operator"].build_plan(case["evidence"], evidence_path=case["evidence_path"],
        evidence_sha256=sha(case["evidence_path"].read_bytes()), runtime=case["runtime"])


def apply(case, frozen):
    return case["operator"].apply_plan(frozen, plan_sha256=case["operator"].digest(frozen), runtime=case["runtime"])


def alter_reference(reference, mutate):
    path = Path(reference["path"])
    value = json.loads(path.read_bytes())
    mutate(value)
    write_json(path, value)
    reference["sha256"] = sha(path.read_bytes())


def alter_journal(case, mutate):
    reference = case["evidence"]["selected"][0]["journal"]
    path = Path(reference["path"])
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    mutate(rows)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    reference["sha256"] = sha(path.read_bytes())


def assert_unchanged(case):
    assert case["runtime"].ledger.writes == []
    assert json.loads(case["runtime"].ledger.path.read_bytes()) == case["initial"]


def test_plan_preserves_evidence_without_an_empty_inventory_fiction_or_write(case):
    frozen = plan(case)
    assert frozen["selected_rows"] == {key: case["initial"]["reservations"][key] for key in SELECTED}
    assert frozen["claim_bytes_to_retire"] == 2_000_000_000
    assert frozen["files_to_delete"] == []
    assert case["runtime"].inventory_calls == []
    assert "inventory" not in frozen
    assert_unchanged(case)


@pytest.mark.parametrize("damage", ["terminal", "canonical_frame"])
def test_historical_refusal_without_complete_canonical_terminal_trace_is_insufficient(case, damage):
    if damage == "terminal":
        alter_journal(case, lambda rows: rows.pop())
    else:
        alter_journal(case, lambda rows: rows[14].update(MESSAGE='  File "/drifted/resource_scheduler.py", line 2137, in acquire'))
    with pytest.raises(case["operator"].CloseoutError):
        plan(case)
    assert_unchanged(case)


@pytest.mark.parametrize("field,bad", [
    ("_PID", "999999"), ("_SYSTEMD_INVOCATION_ID", "e" * 32),
    ("_BOOT_ID", "f" * 32), ("_CMDLINE", "/usr/bin/python3 /drifted/run_legacy_span_cuda.py"),
    ("__REALTIME_TIMESTAMP", "1"), ("_SYSTEMD_USER_UNIT", "unrelated.service"),
])
def test_terminal_trace_trusted_metadata_must_bind_the_failed_invocation(case, field, bad):
    alter_journal(case, lambda rows: rows[-1].update({field: bad}))
    with pytest.raises(case["operator"].CloseoutError):
        plan(case)
    assert_unchanged(case)


@pytest.mark.parametrize("damage", ["request", "native_demand"])
def test_refusal_cannot_authorize_another_request_or_envelope(case, damage):
    reference = case["evidence"]["selected"][0]["refusal"]
    def mutate(value):
        if damage == "request": value["refusal"]["request_id"] = "daemon:another-request"
        else: value["refusal"]["demand"]["additional_memory_mb"] = 1
    alter_reference(reference, mutate)
    with pytest.raises(case["operator"].CloseoutError):
        plan(case)
    assert_unchanged(case)


@pytest.mark.parametrize("field,value", [
    ("attempt_directory", {"path": "/already-attached", "device": 1, "inode": 2}),
    ("child", {"pid": 9, "birth": "9"}),
    ("prior_children", [{"pid": 8, "birth": "8"}]),
    ("external_charges", {"external": {"bytes": 100}}),
    ("reconciliation", {"already": True}),
])
def test_attached_or_previously_reconciled_rows_are_never_unbound(case, field, value):
    ledger = copy.deepcopy(case["initial"])
    ledger["reservations"][SELECTED[0]][field] = value
    write_json(case["runtime"].ledger.path, ledger)
    case["initial"] = ledger
    case["evidence"]["selected"][0]["expected_record_sha256"] = case["operator"].digest(ledger["reservations"][SELECTED[0]])
    with pytest.raises(case["operator"].CloseoutError):
        plan(case)
    assert_unchanged(case)


@pytest.mark.parametrize("birth", ["original-owner", "reused-pid"])
def test_any_live_selected_pid_refuses_even_when_its_birth_changed(case, birth):
    case["runtime"].processes[OWNERS[0]] = {"pid": OWNERS[0], "parent_pid": 1, "birth": birth, "state": "S"}
    with pytest.raises(case["operator"].CloseoutError):
        plan(case)
    assert_unchanged(case)


@pytest.mark.parametrize("damage", ["source", "row", "root", "cap", "evidence_hash"])
def test_frozen_plan_revalidates_every_material_authority_before_write(case, damage):
    frozen = plan(case)
    if damage == "source":
        Path(next(iter(case["evidence"]["source_pins"]))).write_text("# changed source\n")
    elif damage == "evidence_hash":
        with case["evidence_path"].open("a") as stream: stream.write(" ")
    else:
        ledger = copy.deepcopy(case["initial"])
        if damage == "row": ledger["reservations"][SELECTED[1]]["storage_bytes"] -= 1
        elif damage == "root": ledger["roots"][0]["inode"] += 1
        else: ledger["limit_bytes"] += 1
        write_json(case["runtime"].ledger.path, ledger)
        case["initial"] = ledger
    with pytest.raises((case["operator"].CloseoutError, RuntimeError)):
        apply(case, frozen)
    assert_unchanged(case)


def test_census_deadline_expires_before_any_ledger_write(case):
    frozen = plan(case)
    case["runtime"].inventory_delay = 41.0
    with pytest.raises(case["operator"].CloseoutError):
        apply(case, frozen)
    assert_unchanged(case)


@pytest.mark.parametrize("record_type", ["leases", "waiters"])
def test_selected_native_lease_or_waiter_blocks_closeout(case, record_type):
    runtime = case["runtime"]
    record = {"owner_pid": OWNERS[0], "request_id": "different-request"}
    if record_type == "waiters":
        record = {"owner_pid": 999, "request_id": "daemon:" + SELECTED[1]}
    runtime.native_state[record_type]["still-native"] = record
    with pytest.raises(case["operator"].CloseoutError, match="native lease or waiter"):
        plan(case)
    assert_unchanged(case)


@pytest.mark.parametrize("damage", ["absent", "dead", "foreign_owner", "nonancestor", "lane", "envelope", "policy", "boot"])
def test_control_requires_an_actual_live_adequate_validation_ancestor(case, damage):
    runtime = case["runtime"]
    control = runtime.native_state["leases"][runtime.control_lease_id]
    if damage == "absent": del runtime.native_state["leases"][runtime.control_lease_id]
    elif damage == "dead": control["expires_at"] = runtime.wall - 1
    elif damage == "foreign_owner": control["owner_birth_marker"] = "reused-owner-birth"
    elif damage == "nonancestor": runtime.ancestors.clear()
    elif damage == "lane": control["lane"] = "hammer_lean"
    elif damage == "envelope": control["memory_mb"] = 512
    elif damage == "policy": runtime.native_state["config"]["private_native_test_policy"] = 2
    else: runtime.current_boot_id = "e" * 32
    with pytest.raises(case["operator"].CloseoutError):
        plan(case)
    assert_unchanged(case)


def test_exact_two_row_atomic_closeout_preserves_active_foreign_body_and_observed_bytes(case):
    frozen = plan(case)
    result = apply(case, frozen)
    assert len(case["runtime"].ledger.writes) == 1
    saved = json.loads(case["runtime"].ledger.path.read_bytes())
    assert set(saved["reservations"]) == set(case["initial"]["reservations"])
    assert saved["limit_bytes"] == case["initial"]["limit_bytes"]
    assert saved["roots"] == case["initial"]["roots"]
    assert saved["reservations"][PROTECTED] == case["initial"]["reservations"][PROTECTED]
    for reservation_id in SELECTED:
        before, after = case["initial"]["reservations"][reservation_id], saved["reservations"][reservation_id]
        assert after["status"] == "released"
        assert after["storage_bytes"] == before["storage_bytes"] == 1_000_000_000
        assert after["last_usage"] == before["last_usage"]
        assert after["artifacts_durable_asserted"] is False
        assert after["attempt_directory"] is None and after["child"] is None
    assert case["runtime"].inventory["apparent_bytes"] == 700_000_123
    assert result["status"] == "applied_and_observed"
    assert result["claim_bytes_retired"] == 2_000_000_000
    assert result["physical_bytes_deleted"] == 0
    assert result["full_claim_accounting"]["observed_apparent_bytes"] == 700_000_123
    assert result["actual_postwrite_census"]["observed_apparent_bytes"] == 700_000_123
    assert result["full_claim_accounting"]["outstanding_full_reservations_bytes"] - result["actual_postwrite_census"]["outstanding_full_reservations_bytes"] == 2_000_000_000
    assert len(case["runtime"].inventory_calls) == 2
    assert all(0 < seconds <= 25 for seconds in case["runtime"].inventory_calls)


def test_postwrite_inventory_failure_reports_partial_outcome_without_rollback(case):
    frozen = plan(case)
    case["runtime"].inventory_error = TimeoutError("second actual census timed out")
    case["runtime"].inventory_error_on_call = 2
    result = apply(case, frozen)
    assert result["status"] == "applied_requires_postverification"
    assert result["committed"] is True
    assert result["rollback_attempted"] is False
    assert result["postwrite_error_type"] == "TimeoutError"
    assert result["claim_bytes_retired"] == 2_000_000_000
    assert "actual_postwrite_census" not in result
    assert len(case["runtime"].ledger.writes) == 1
    saved = json.loads(case["runtime"].ledger.path.read_bytes())
    assert all(saved["reservations"][key]["status"] == "released" for key in SELECTED)
    assert saved["reservations"][PROTECTED] == case["initial"]["reservations"][PROTECTED]


def test_write_exception_before_persistence_reports_uncertain_outcome_without_rollback(case):
    frozen = plan(case)
    def fail_before_write():
        raise OSError("private ledger refused write before persistence")
    case["runtime"].ledger.before_write = fail_before_write
    result = apply(case, frozen)
    assert result["status"] == "write_outcome_requires_verification"
    assert result["write_attempted"] is True and result["committed"] is False
    assert result["rollback_attempted"] is False
    assert result["write_or_readback_error_type"] == "OSError"
    assert "claim_bytes_retired" not in result
    assert case["runtime"].inventory_calls == [25.0]
    assert_unchanged(case)


def test_write_exception_after_persistence_keeps_uncertain_receipt_and_released_rows(case):
    frozen = plan(case)
    def fail_after_write():
        raise OSError("private ledger persisted before durability failure")
    case["runtime"].ledger.after_write = fail_after_write
    result = apply(case, frozen)
    assert result["status"] == "write_outcome_requires_verification"
    assert result["write_attempted"] is True and result["committed"] is False
    assert result["rollback_attempted"] is False
    assert result["write_or_readback_error_type"] == "OSError"
    assert "claim_bytes_retired" not in result
    assert len(case["runtime"].ledger.writes) == 1
    saved = json.loads(case["runtime"].ledger.path.read_bytes())
    assert all(saved["reservations"][key]["status"] == "released" for key in SELECTED)
    assert saved["reservations"][PROTECTED] == case["initial"]["reservations"][PROTECTED]
    assert case["runtime"].inventory_calls == [25.0]


def test_fresh_foreign_active_body_survives_legitimate_update_between_plan_and_apply(case):
    frozen = plan(case)
    fresh = copy.deepcopy(case["initial"])
    fresh["reservations"][PROTECTED]["opaque_foreign_body"] = {
        "must": ["preserve", "newer", "progress"], "published_batches": 19,
    }
    fresh["reservations"][PROTECTED]["progress_receipt"] = "new-active-owner-receipt"
    write_json(case["runtime"].ledger.path, fresh)
    result = apply(case, frozen)
    saved = json.loads(case["runtime"].ledger.path.read_bytes())
    assert result["status"] == "applied_and_observed"
    assert len(case["runtime"].ledger.writes) == 1
    assert saved["reservations"][PROTECTED] == fresh["reservations"][PROTECTED]
    assert saved["reservations"][PROTECTED] != case["initial"]["reservations"][PROTECTED]
    assert result["other_reservations_sha256"] == case["operator"].digest({PROTECTED: fresh["reservations"][PROTECTED]})
    assert result["foreign_rows_preserved_in_transaction"] is True
    assert all(saved["reservations"][key]["status"] == "released" for key in SELECTED)

