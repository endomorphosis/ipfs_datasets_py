#!/usr/bin/env python3
"""Explicitly retire two reviewed, unbound native-admission promises.

This profile never admits work, expires claims, invents an artifact inventory,
or reconciles an attached attempt. Run under an existing native VALIDATION
lease. Plan generation is read-only; apply requires the exact plan hash.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time


EVIDENCE_SCHEMA = "trusted-unbound-admission-closeout-evidence/v1"
PLAN_SCHEMA = "explicit-failed-unbound-native-admission-closeout-plan/v1"
RESULT_SCHEMA = "explicit-failed-unbound-native-admission-closeout/v1"
ALLOWED_RESERVATIONS = {
    "6eb0cccf427e4ac79e76f15b888313e0": 1020862,
    "36b6e6ce4be8463fae8cadaa828a4177": 1070490,
}
LIMIT_BYTES = 160_000_000_000
REQUIRED_SOURCES = (
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/resource_scheduler.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/existing_resource_scheduler.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legacy_span_campaign_resources.py",
    "scripts/ops/legal_ir/run_legacy_span_cuda.py",
)
ROW_FIELDS = set("artifacts_durable_asserted attempt_directory child child_process_slots cpu_slots created_at external_charges last_usage memory_mb owner_pid prior_children reservation_id retention_reason scheduler_lane status storage_bytes workload".split())
MAX_INPUT_BYTES = 4 * 1024 * 1024


class CloseoutError(RuntimeError):
    pass


def need(condition, message):
    if not condition:
        raise CloseoutError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _pairs(items):
    result = {}
    for key, value in items:
        need(key not in result, "duplicate JSON field")
        result[key] = value
    return result


def _json(raw):
    try:
        return json.loads(raw, object_pairs_hook=_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(CloseoutError("nonfinite JSON value")))
    except (ValueError, UnicodeError) as error:
        raise CloseoutError("invalid JSON") from error


def _sha(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _read(path):
    path = Path(path)
    need(path.is_absolute(), "absolute evidence path required")
    for parent in (*reversed(path.parents), path.parent):
        need(stat.S_ISDIR(parent.lstat().st_mode), "evidence directory must not be a symlink")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        before = os.fstat(stream.fileno())
        need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
             and before.st_uid == os.geteuid() and 0 < before.st_size <= MAX_INPUT_BYTES,
             "bounded owned unaliased evidence file required")
        raw = stream.read(MAX_INPUT_BYTES + 1)
        after = os.fstat(stream.fileno())
    identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    need(len(raw) == before.st_size and identity(before) == identity(after)
         and identity(after) == identity(path.lstat()), "evidence changed while reading")
    return raw


def _reference(reference, *, json_value=True):
    need(type(reference) is dict and _sha(reference.get("sha256")), "hashed evidence reference required")
    raw = _read(reference["path"])
    need(hashlib.sha256(raw).hexdigest() == reference["sha256"], "evidence hash differs")
    return _json(raw) if json_value else raw


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _journal_proof(item, evidence, row):
    raw = _reference(item["journal"], json_value=False)
    lines = [_json(line) for line in raw.splitlines() if line.strip()]
    need(10 <= len(lines) <= 100, "complete bounded terminal traceback required")
    runner = str(Path(evidence["workspace_tree"]) / REQUIRED_SOURCES[-1])
    messages, times = [], []
    for line in lines:
        need(type(line) is dict and line.get("_PID") == str(item["owner_pid"])
             and line.get("_SYSTEMD_INVOCATION_ID") == item["invocation_id"]
             and line.get("_BOOT_ID") == item["boot_id"]
             and line.get("_UID") == str(os.geteuid())
             and line.get("_SYSTEMD_USER_UNIT") == "legacy-cuda-span-census.service"
             and runner in line.get("_CMDLINE", ""), "terminal journal owner or invocation differs")
        need(type(line.get("MESSAGE")) is str, "terminal journal message required")
        timestamp = line.get("__REALTIME_TIMESTAMP")
        need(type(timestamp) is str and timestamp.isdecimal(), "trusted journal timestamp required")
        times.append(int(timestamp) / 1_000_000)
        messages.append(line["MESSAGE"])
    need(times == sorted(times) and row["created_at"] <= times[0] <= times[-1]
         and times[-1] - row["created_at"] < 120, "terminal traceback timing differs")
    text = "\n".join(messages)
    need(messages[0] == "Traceback (most recent call last):"
         and messages.count(messages[0]) == 1
         and messages[-1] == "ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler.LeaseTimeoutError: timed out waiting for a resource lease",
         "actual terminal native LeaseTimeoutError required")
    root = evidence["workspace_tree"]
    required = [
        (REQUIRED_SOURCES[-1], "main"),
        (REQUIRED_SOURCES[3], "open"),
        (REQUIRED_SOURCES[0], "__enter__"),
        (REQUIRED_SOURCES[0], "_acquire_native_lease"),
        (REQUIRED_SOURCES[1], "acquire"),
    ]
    cursor = 0
    for relative, function in required:
        pattern = r'  File "' + re.escape(str(Path(root) / relative)) + r'", line [0-9]+, in ' + function + r"\n"
        found = re.search(pattern, text[cursor:])
        need(found is not None, "canonical terminal acquisition frame sequence differs")
        cursor += found.end()
    for statement in ("    resource.open()", "    self.reservation.__enter__()",
                      "    self._lease = self._acquire_native_lease(scheduler, scheduler_lane)", "    raise error"):
        need(statement in messages, "canonical no-grant control-flow trace differs")
    return {"journal_sha256": item["journal"]["sha256"], "invocation_id": item["invocation_id"],
            "boot_id": item["boot_id"], "terminal_at": times[-1], "terminal": "LeaseTimeoutError"}


def _selected_row(row, item):
    need(type(row) is dict and set(row) == ROW_FIELDS, "unbound reservation field inventory differs")
    need(digest(row) == item["expected_record_sha256"], "selected reservation hash differs")
    need(row["reservation_id"] == item["reservation_id"] and row["owner_pid"] == item["owner_pid"]
         and row["status"] == "retained" and row["retention_reason"] == "scheduler_admission_failed"
         and row["attempt_directory"] is None and row["child"] is None
         and row["prior_children"] == [] and row["external_charges"] == {}
         and row["artifacts_durable_asserted"] is False
         and row["storage_bytes"] == 1_000_000_000
         and row["cpu_slots"] == 3 and row["memory_mb"] == 8192
         and row["child_process_slots"] == 5 and row["scheduler_lane"] == "hammer_lean"
         and row["workload"] == "canonical_trainer" and _finite(row["created_at"]),
         "selected reservation is not the reviewed unbound failure")


def validate_evidence(evidence, runtime):
    need(type(evidence) is dict and evidence.get("schema") == EVIDENCE_SCHEMA, "invalid evidence schema")
    need(Path(evidence["workspace_tree"]) == runtime.workspace_tree
         and evidence.get("limit_bytes") == LIMIT_BYTES, "workspace or cap differs")
    need(type(evidence.get("roots")) is list and evidence["roots"], "original storage roots required")
    need(_sha(evidence["scheduler"]["policy_sha256"]), "exact native policy required")
    pins = evidence.get("source_pins")
    need(type(pins) is dict and all(_sha(value) for value in pins.values()), "source pins required")
    need(all(str(runtime.workspace_tree / relative) in pins for relative in REQUIRED_SOURCES),
         "all authoritative no-grant producer pins required")
    selected = evidence.get("selected")
    need(type(selected) is list and len(selected) == 2, "exact two reviewed reservations required")
    need({item.get("reservation_id"): item.get("owner_pid") for item in selected} == ALLOWED_RESERVATIONS,
         "reservation allowlist differs")
    need(all(_sha(item.get("expected_record_sha256")) and re.fullmatch(r"[0-9a-f]{32}", item.get("invocation_id", ""))
             and re.fullmatch(r"[0-9a-f]{32}", item.get("boot_id", "")) for item in selected), "exact historical identities required")
    protected = evidence["protected_active_owner"]
    need(protected["reservation_id"] not in ALLOWED_RESERVATIONS
         and type(protected["pid"]) is int and protected["pid"] > 0
         and type(protected["birth"]) is str and protected["birth"].isdecimal(), "protected active owner required")
    runtime.guard_sources(evidence)
    return evidence


def _protected_owner(evidence, runtime, ledger):
    protected = evidence["protected_active_owner"]
    active = ledger["reservations"].get(protected["reservation_id"], {})
    process = runtime.process(protected["pid"])
    need(active.get("status") == "active" and active.get("owner_pid") == protected["pid"]
         and process is not None and process["birth"] == protected["birth"]
         and process.get("state") != "Z", "protected census owner changed or stopped")


def _verify_rows(evidence, runtime, ledger):
    need(ledger["roots"] == evidence["roots"] and ledger["limit_bytes"] == LIMIT_BYTES,
         "original ledger roots or cap changed")
    proofs = {}
    for item in evidence["selected"]:
        row = ledger["reservations"].get(item["reservation_id"])
        _selected_row(row, item)
        need(runtime.process(item["owner_pid"]) is None, "failed owner PID exists or was reused")
        proof = _journal_proof(item, evidence, row)
        refusal = _reference(item["refusal"])
        for key in item["refusal"].get("keys", []):
            refusal = refusal[key]
        need(refusal.get("schema") == "proof-resource-admission-refusal@1"
             and refusal.get("request_id") == "daemon:" + item["reservation_id"]
             and refusal.get("lane") == row["scheduler_lane"] and refusal.get("parent_lease_id") is None
             and refusal.get("historical") is True and refusal.get("reason") in {"proof_pid_headroom", "proof_memory_headroom"}
             and _finite(refusal.get("decision_cycle_at"))
             and row["created_at"] <= refusal["decision_cycle_at"] <= proof["terminal_at"],
             "matching native refusal evidence required")
        need(refusal.get("demand", {}).get("additional_memory_mb") == row["memory_mb"]
             and refusal.get("demand", {}).get("additional_process_slots") == row["child_process_slots"],
             "native refusal demand differs from reviewed request")
        receipt = _reference(item["execution_receipt"])
        need(str(receipt.get("service_after", {}).get("MainPID")) == str(item["owner_pid"])
             and receipt.get("service_before", {}).get("MainPID") == "0"
             and receipt.get("service_after", {}).get("NRestarts") == "0"
             and receipt.get("storage_limit_bytes") == LIMIT_BYTES
             and receipt.get("attempt_storage_bytes") == row["storage_bytes"]
             and receipt.get("policy_sha256") == evidence["scheduler"]["policy_sha256"]
             and _finite(receipt.get("started_at_unix"))
             and receipt["started_at_unix"] <= row["created_at"] < receipt["started_at_unix"] + 120,
             "matching single-start execution receipt required")
        proofs[item["reservation_id"]] = proof
    _protected_owner(evidence, runtime, ledger)
    return proofs


def _foreign(ledger):
    return {key: value for key, value in ledger["reservations"].items() if key not in ALLOWED_RESERVATIONS}


def validate_native_snapshot(evidence, state, *, control_lease_id, ancestors, current_boot_id, now):
    """Validate a caller-locked actual snapshot without altering native state."""
    need(type(state) is dict and type(state.get("leases")) is dict
         and type(state.get("waiters")) is dict
         and digest(state.get("config")) == evidence["scheduler"]["policy_sha256"],
         "native snapshot or original policy differs")
    for name in ("leases", "waiters"):
        for row in state[name].values():
            need(row.get("owner_pid") not in ALLOWED_RESERVATIONS.values()
                 and row.get("request_id") not in {"daemon:" + key for key in ALLOWED_RESERVATIONS},
                 "failed owner still has a native lease or waiter")
    need(type(current_boot_id) is str, "current local boot identity required")
    boot = current_boot_id.replace("-", "")
    need(re.fullmatch(r"[0-9a-f]{32}", boot) is not None
         and all(item["boot_id"] == boot for item in evidence["selected"]),
         "historical journal is not from the current local boot")
    control = state["leases"].get(control_lease_id)
    need(control is None or (type(control) is dict and all(type(control.get(key)) is int
         for key in ("cpu_slots", "memory_mb", "child_process_slots", "owner_pid"))),
         "typed native control envelope required")
    need(control is not None and control.get("lane") == "validation"
         and control.get("parent_lease_id") is None and not control.get("cancelled")
         and not control.get("release_requested") and _finite(control.get("expires_at"))
         and control["expires_at"] > now and control.get("cpu_slots", 0) >= 1
         and control.get("memory_mb", 0) >= 1536 and control.get("child_process_slots", 0) >= 4,
         "live adequate native VALIDATION control root required")
    owner = ancestors.get(control.get("owner_pid"))
    need(owner is not None and owner.get("state") != "Z"
         and owner.get("birth") == control.get("owner_birth_marker")
         and str(control.get("owner_boot_id", "")).replace("-", "") == boot,
         "native control owner is not the actual live ancestor")
    return {"control_lease_id": control_lease_id, "control_owner_pid": control["owner_pid"],
            "policy_sha256": evidence["scheduler"]["policy_sha256"], "matching_failed_native_records": 0,
            "state_mutated": False, "new_lease_acquired": False}


def build_plan(evidence, *, evidence_path, evidence_sha256, runtime):
    need(_sha(evidence_sha256) and hashlib.sha256(_read(evidence_path)).hexdigest() == evidence_sha256
         and _json(_read(evidence_path)) == evidence, "exact frozen evidence required")
    validate_evidence(evidence, runtime)
    native = runtime.native_check(evidence)
    helper = runtime.helper(evidence)
    with helper._locked():
        ledger = helper._read()
        proofs = _verify_rows(evidence, runtime, ledger)
        rows = {key: copy.deepcopy(ledger["reservations"][key]) for key in ALLOWED_RESERVATIONS}
    return {"schema": PLAN_SCHEMA, "evidence": {"path": str(Path(evidence_path)), "sha256": evidence_sha256},
            "producer_script_sha256": hashlib.sha256(_read(Path(__file__).absolute())).hexdigest(),
            "selected_rows": rows, "terminal_no_grant_proofs": proofs,
            "claim_bytes_to_retire": 2_000_000_000, "storage_cap_bytes": LIMIT_BYTES,
            "native_observation": native, "files_to_delete": [], "automatic_expiry": False,
            "admitted": False, "Lean_admitted": False}


def validate_plan(plan, runtime):
    need(type(plan) is dict and plan.get("schema") == PLAN_SCHEMA
         and plan.get("claim_bytes_to_retire") == 2_000_000_000
         and plan.get("storage_cap_bytes") == LIMIT_BYTES and plan.get("files_to_delete") == []
         and plan.get("automatic_expiry") is False and plan.get("admitted") is False
         and plan.get("Lean_admitted") is False, "invalid explicit closeout plan")
    need(plan.get("producer_script_sha256") == hashlib.sha256(_read(Path(__file__).absolute())).hexdigest(),
         "operator producer differs from reviewed plan")
    evidence = validate_evidence(_reference(plan["evidence"]), runtime)
    need(set(plan.get("selected_rows", {})) == set(ALLOWED_RESERVATIONS), "plan selected rows differ")
    for item in evidence["selected"]:
        _selected_row(plan["selected_rows"][item["reservation_id"]], item)
    return evidence


def _accounting(evidence, ledger, inventory, runtime):
    need(type(inventory) is dict and set(inventory) == {"apparent_bytes", "entry_count", "symlink_count", "special_file_count"}
         and all(type(value) is int and value >= 0 for value in inventory.values()), "actual native inventory required")
    outstanding = sum(row["storage_bytes"] for row in ledger["reservations"].values() if row["status"] != "released")
    free = min(runtime.filesystem_free(Path(root["path"])) for root in evidence["roots"])
    charged = inventory["apparent_bytes"] + outstanding
    return {"scope": "named_roots_only_apparent_bytes", "inventory": inventory,
            "observed_apparent_bytes": inventory["apparent_bytes"], "outstanding_full_reservations_bytes": outstanding,
            "additional_requested_bytes": 0, "charged_bytes": charged, "limit_bytes": LIMIT_BYTES,
            "minimum_filesystem_free_bytes": free, "over_limit_bytes": max(0, charged - LIMIT_BYTES),
            "filesystem_free_shortfall_bytes": max(0, outstanding - free), "admitted": False}


def apply_plan(plan, *, plan_sha256, runtime):
    need(_sha(plan_sha256) and digest(plan) == plan_sha256, "exact canonical plan hash required")
    evidence = validate_plan(plan, runtime)
    runtime.native_check(evidence)
    helper = runtime.helper(evidence)
    result = {"schema": RESULT_SCHEMA, "plan_sha256": plan_sha256, "status": "not_applied",
              "cap_changed": False, "automatic_expiry": False, "files_deleted": False,
              "new_resource_lease_acquired": False, "admitted": False, "Lean_admitted": False,
              "Constitution_formalized": False}
    try:
        with helper._locked():
            deadline = runtime.clock() + runtime.lock_hold_seconds
            ledger = helper._read()
            proofs = _verify_rows(evidence, runtime, ledger)
            need(all(ledger["reservations"][key] == row for key, row in plan["selected_rows"].items()),
                 "selected row changed after planning")
            foreign = copy.deepcopy(_foreign(ledger))
            inventory = runtime.census(evidence, timeout_seconds=min(runtime.inventory_timeout_seconds, deadline - runtime.clock() - 8))
            before = _accounting(evidence, ledger, inventory, runtime)
            runtime.guard_sources(evidence)
            native = runtime.native_check(evidence)
            _verify_rows(evidence, runtime, ledger)
            need(runtime.clock() < deadline - 5, "closeout disk-lock deadline exhausted before write")
            released_at = runtime.wall_time()
            for key, previous in plan["selected_rows"].items():
                ledger["reservations"][key].update(status="released", released_at=released_at,
                    explicit_unbound_reconciliation={"schema": RESULT_SCHEMA, "plan_sha256": plan_sha256,
                        "previous_record_sha256": digest(previous), "original_owner_pid": previous["owner_pid"],
                        "reconciled_by_pid": os.getpid(), "claim_bytes_retired": previous["storage_bytes"],
                        "terminal_no_grant_proof": proofs[key], "other_reservations_sha256": digest(foreign),
                        "artifacts_durable_asserted": False, "attached_attempt": False,
                        "outputs_deleted": False, "automatic_expiry": False, "admitted": False})
            need(_foreign(ledger) == foreign, "foreign reservation changed in transaction")
            result.update(write_attempted=True, committed=False,
                status="write_outcome_requires_verification",
                selected_rows_after={key: copy.deepcopy(ledger["reservations"][key]) for key in ALLOWED_RESERVATIONS},
                other_reservations_sha256=digest(foreign), full_claim_accounting=before,
                native_observation=native, postwrite_observation_is_separate_transaction=True)
            helper._write(ledger)
            result.update(committed=True, status="applied_requires_postverification")
            after = helper._read()
            need(after == ledger and _foreign(after) == foreign, "atomic closeout readback differs")
            projected = _accounting(evidence, after, inventory, runtime)
            need(before["outstanding_full_reservations_bytes"] - projected["outstanding_full_reservations_bytes"] == 2_000_000_000,
                 "retired promise accounting differs")
            result.update(foreign_rows_preserved_in_transaction=True,
                projected_accounting=projected, projected_inventory_is_prewrite=True,
                claim_bytes_retired=2_000_000_000, physical_bytes_deleted=0)
    except Exception as error:
        if not result.get("write_attempted"):
            raise
        result.update(write_or_readback_error_type=type(error).__name__,
                      write_or_readback_error=str(error), rollback_attempted=False)
        return result
    # Yield to the live census before a second independent bounded lock section.
    runtime.sleep(0.1)
    try:
        runtime.native_check(evidence)
        with helper._locked():
            deadline = runtime.clock() + runtime.lock_hold_seconds
            after = helper._read()
            need(after["roots"] == evidence["roots"] and after["limit_bytes"] == LIMIT_BYTES,
                 "postwrite ledger scope differs")
            need(all(after["reservations"].get(key) == row for key, row in result["selected_rows_after"].items()),
                 "closed row changed before postwrite observation")
            _protected_owner(evidence, runtime, after)
            inventory = runtime.census(evidence, timeout_seconds=min(runtime.inventory_timeout_seconds, deadline - runtime.clock() - 8))
            accounting = _accounting(evidence, after, inventory, runtime)
            runtime.guard_sources(evidence)
            runtime.native_check(evidence)
            _protected_owner(evidence, runtime, after)
            need(runtime.clock() < deadline - 2, "postwrite observation deadline exceeded")
        result.update(status="applied_and_observed", actual_postwrite_census=accounting,
            postwrite_observed_at=runtime.wall_time())
    except Exception as error:
        need(result.get("committed") is True, "internal closeout commit state differs")
        result.update(status="applied_requires_postverification", postwrite_error_type=type(error).__name__,
                      postwrite_error=str(error), rollback_attempted=False)
    return result


class Runtime:
    """Actual canonical runtime; tests may inject an explicitly isolated facade."""
    def __init__(self, workspace_tree, control_lease_id, inventory_timeout_seconds=25, lock_hold_seconds=40):
        self.workspace_tree = Path(workspace_tree).absolute()
        self.control_lease_id = control_lease_id
        need(type(control_lease_id) is str and re.fullmatch(r"[0-9a-f]{32}", control_lease_id), "existing public control lease ID required")
        need(_finite(inventory_timeout_seconds) and 0 < inventory_timeout_seconds <= 30
             and _finite(lock_hold_seconds) and 35 <= lock_hold_seconds <= 45,
             "bounded inventory and disk-lock deadlines required")
        self.inventory_timeout_seconds, self.lock_hold_seconds = inventory_timeout_seconds, lock_hold_seconds
        for name, module in tuple(sys.modules.items()):
            if name == "ipfs_datasets_py" or name.startswith("ipfs_datasets_py."):
                origin = getattr(module, "__file__", None)
                need(origin is None or Path(origin).absolute().is_relative_to(self.workspace_tree), "drifted datasets package was imported first")
        sys.path.insert(0, str(self.workspace_tree))
        prefix = "ipfs_datasets_py.optimizers.logic_theorem_optimizer."
        self.native = importlib.import_module(prefix + "autoencoder_daemon_resources")
        self.existing = importlib.import_module(prefix + "existing_resource_scheduler")
        for module in (self.native, self.existing, self.existing.native):
            need(Path(module.__file__).absolute().is_relative_to(self.workspace_tree), "canonical native producer required")
        self.clock, self.wall_time, self.sleep = time.monotonic, time.time, time.sleep

    def guard_sources(self, evidence):
        historical = _reference(evidence["historical_source_binding"])["source_sha256"]
        for path, expected in evidence["source_pins"].items():
            need(historical.get(path) == expected and hashlib.sha256(_read(path)).hexdigest() == expected,
                 "actual producer differs from historical no-grant binding")

    def process(self, pid):
        return self.native._process(pid)

    def filesystem_free(self, root):
        return self.native.shutil.disk_usage(root).free

    def helper(self, evidence):
        helper = self.native.DaemonResourceReservation(evidence["ledger_path"],
            roots=[row["path"] for row in evidence["roots"]], storage_bytes=1, memory_mb=1,
            require_existing_ledger=True, ledger_lock_timeout_seconds=5)
        need(helper.root_identities == evidence["roots"], "original root identity differs")
        return helper

    def native_check(self, evidence):
        # The canonical native flock blocks. Bound it outside that module,
        # without monkeypatching its lock or changing its persisted state.
        return self._subprocess(evidence, "--_native-check-child", timeout_seconds=3)

    def _native_check(self, evidence):
        self.guard_sources(evidence)
        scheduler = self.existing.open_existing_scheduler(evidence["scheduler"]["state_path"],
            evidence["scheduler"]["policy_sha256"])
        with scheduler._locked_state(persist=False) as state:
            ancestors, pid = {}, os.getpid()
            for _ in range(64):
                process = self.process(pid)
                need(process is not None and process["state"] != "Z", "control ancestry disappeared")
                ancestors[pid] = process
                if pid == 1:
                    break
                pid = process["parent_pid"]
            for pid in ALLOWED_RESERVATIONS.values():
                need(self.process(pid) is None, "failed owner PID exists or was reused")
            return validate_native_snapshot(evidence, state, control_lease_id=self.control_lease_id,
                ancestors=ancestors, current_boot_id=self.existing.native._owner_boot_id(), now=time.time())

    def census(self, evidence, timeout_seconds):
        need(_finite(timeout_seconds) and 0 < timeout_seconds <= 30, "positive bounded census budget required")
        return self._subprocess(evidence, "--_inventory-child", timeout_seconds=timeout_seconds)

    def _subprocess(self, evidence, flag, timeout_seconds):
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", IPFS_DATASETS_PY_MINIMAL_IMPORTS="1",
            IPFS_DATASETS_AUTO_INSTALL="0", IPFS_ACCELERATE_SKIP_CORE="1")
        command = [sys.executable, "-B", str(Path(__file__).absolute()), flag,
                   "--workspace-tree", str(self.workspace_tree), "--control-lease-id", self.control_lease_id]
        payload = json.dumps(evidence, sort_keys=True, allow_nan=False).encode()
        child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 env=environment, cwd=self.workspace_tree)
        try:
            out, error = child.communicate(payload, timeout=timeout_seconds)
        except subprocess.TimeoutExpired as error:
            child.kill()
            child.communicate(timeout=3)
            raise CloseoutError("bounded actual native observation timed out") from error
        need(child.returncode == 0 and len(out) <= 4096 and len(error) <= 4096,
             "actual native observation subprocess failed")
        return _json(out)


def _write_result(path, value):
    path = Path(path)
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", nargs="?", choices=("plan", "apply"))
    parser.add_argument("--workspace-tree", type=Path, required=True)
    parser.add_argument("--control-lease-id", default=os.environ.get("IPFS_DATASETS_UNBOUND_CONTROL_LEASE_ID"))
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--evidence-sha256")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--plan-sha256", help="canonical JSON digest printed by plan mode")
    parser.add_argument("--result", type=Path)
    parser.add_argument("--_inventory-child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--_native-check-child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    runtime = Runtime(args.workspace_tree, args.control_lease_id)
    if args._inventory_child or args._native_check_child:
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        need(len(raw) <= MAX_INPUT_BYTES, "bounded child evidence required")
        evidence = validate_evidence(_json(raw), runtime)
        proof = runtime._native_check(evidence)
        if args._native_check_child:
            print(json.dumps(proof, sort_keys=True))
            return 0
        roots = [Path(row["path"]) for row in evidence["roots"]]
        need([runtime.native._root_identity(root) for root in roots] == evidence["roots"], "inventory root identity differs")
        inventory = runtime.native._inventory(roots)
        runtime.guard_sources(evidence)
        runtime._native_check(evidence)
        print(json.dumps(inventory, sort_keys=True))
        return 0
    need(args.mode is not None and args.result is not None and not args.result.exists(), "mode and new result path required")
    if args.mode == "plan":
        need(args.evidence is not None and _sha(args.evidence_sha256), "frozen evidence path and SHA256 required")
        evidence = _reference({"path": str(args.evidence.absolute()), "sha256": args.evidence_sha256})
        plan = build_plan(evidence, evidence_path=args.evidence.absolute(), evidence_sha256=args.evidence_sha256, runtime=runtime)
        _write_result(args.result, plan)
        print(json.dumps({"status": "reviewable_plan", "plan_sha256": digest(plan), "result": str(args.result)}))
        return 0
    need(args.plan is not None and _sha(args.plan_sha256), "exact reviewed plan required")
    plan = _json(_read(args.plan.absolute()))
    result = apply_plan(plan, plan_sha256=args.plan_sha256, runtime=runtime)
    _write_result(args.result, result)
    print(json.dumps({"status": result["status"], "result": str(args.result)}))
    return 0 if result["status"] == "applied_and_observed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
