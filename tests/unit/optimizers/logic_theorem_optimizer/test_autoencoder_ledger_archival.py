"""Pure archival protocol controls and explicit private Native fixtures.

The direct unittest entry selects MemoryProtocolTests, whose controls remain
effect-free. NativeProfileTests is selected separately under the existing
owned validator and retains its private metadata for the outer evidence seal.
"""
from contextlib import contextmanager
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as base

MODULE_PATH = Path(base.__file__).with_name("autoencoder_ledger_archival.py")
MODULE_NAME = "ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_ledger_archival"
spec = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
sdk = importlib.util.module_from_spec(spec)
sys.modules[MODULE_NAME] = sdk
spec.loader.exec_module(sdk)

ID = "1" * 32
OTHER = "2" * 32
ADMIN = "3" * 32


def inputs():
    original = {"reservation_id": ID, "status": "released", "owner_pid": 101,
        "storage_bytes": 1048576, "memory_mb": 256, "cpu_slots": 1, "child_process_slots": 1,
        "attempt_directory": {"path": "/named/owned-previous-attempt", "device": 1, "inode": 12},
        "artifacts_durable_asserted": True, "external_charges": {"preserve-this": 4096},
        "final_accounting": {"charged_bytes": 123456, "inventory": {"apparent_bytes": 123}},
        "explicit_reconciliation": {"schema": "authored-recovery-fixture/v1", "proof": "p" * 131072,
                                    "full_history": {"nested": [1, 2, {"event": "retained then released"}]}}}
    foreign = {"reservation_id": OTHER, "status": "active", "owner_pid": 202,
        "storage_bytes": 524288, "attempt_directory": {"path": "/named/foreign-active", "device": 1, "inode": 13},
        "external_charges": {}, "artifacts_durable_asserted": False,
        "opaque_authority_free_metadata": {"unchanged": [1, 2, 3]}}
    ledger = {"schema": "daemon-resource-reservations-v1", "roots": [{"path": "/named", "device": 1, "inode": 2}],
              "limit_bytes": 160000000000, "reservations": {ID: original, OTHER: foreign}}
    selection = {"reservation_id": ID, "expected_record_sha256": sdk.digest(original),
        "expected_reconciliation_sha256": sdk.digest(original["explicit_reconciliation"]),
        "expected_owner_pid": 101, "expected_attempt_path": "/named/owned-previous-attempt"}
    admin = {"reservation_id": ADMIN, "status": "released", "owner_pid": 303,
             "storage_bytes": 33554432, "artifacts_durable_asserted": True,
             "memory_mb": 256, "cpu_slots": 1, "child_process_slots": 1,
             "scheduler_lane": "orchestration", "child": None, "prior_children": [], "external_charges": {},
             "last_usage": {"observed_apparent_bytes": 123456}, "archival": {"schema": sdk.SCHEMA},
             "native_lease_id": "fixture-phase", "parent_lease_id": "fixture-root",
             "scheduler_state_path": "/named/fixture-scheduler.json", "scheduler_policy_sha256": "f" * 64,
             "attempt_directory": {"path": "/named/private-history", "device": 1, "inode": 14},
             "workload": "canonical_resource_ledger_archival"}
    return ledger, [selection], admin


def plan(ledger=None, selections=None, admin=None, snapshot="/named/private-history/ledger-before.private.json"):
    baseline = inputs()
    return sdk.plan_reconciliation_archival(sdk.wire(baseline[0] if ledger is None else ledger),
        selections=baseline[1] if selections is None else selections, snapshot_path=snapshot,
        administration_record=baseline[2] if admin is None else admin)


class MemoryProtocolTests(unittest.TestCase):
    def capacity(self):
        return {"observed_apparent_bytes": sdk.MAX_STORAGE_BYTES - 100,
                "outstanding_full_reservations_bytes": 40, "additional_requested_bytes": 60,
                "charged_bytes": sdk.MAX_STORAGE_BYTES, "limit_bytes": sdk.MAX_STORAGE_BYTES,
                "minimum_filesystem_free_bytes": 100}

    def test_capacity_exact_boundary_is_accepted_without_a_grant(self):
        self.assertTrue(sdk.check_capacity_precharge(self.capacity(), 60))

    def test_capacity_one_byte_over_cap_is_refused(self):
        observation = self.capacity()
        observation["observed_apparent_bytes"] += 1
        observation["charged_bytes"] += 1
        with self.assertRaisesRegex(sdk.ArchivalRefusal, "precharge does not fit"):
            sdk.check_capacity_precharge(observation, 60)

    def test_capacity_full_outstanding_and_archive_need_real_free_space(self):
        observation = self.capacity()
        observation["minimum_filesystem_free_bytes"] = 99
        with self.assertRaisesRegex(sdk.ArchivalRefusal, "precharge does not fit"):
            sdk.check_capacity_precharge(observation, 60)

    def test_capacity_projection_cannot_omit_archive_amplification(self):
        observation = self.capacity()
        observation["charged_bytes"] -= 60
        with self.assertRaisesRegex(sdk.ArchivalRefusal, "projection or cap differs"):
            sdk.check_capacity_precharge(observation, 60)

    def test_roundtrip_recovers_entire_exact_record_and_raw_snapshot(self):
        ledger, selections, admin = inputs()
        raw = sdk.wire(ledger)
        result = plan(ledger, selections, admin)
        self.assertEqual(result["snapshot_bytes"], raw)
        self.assertEqual(sdk.restore_archived_record(raw, result["ledger"]["reservations"][ID]), ledger["reservations"][ID])
        self.assertGreater(result["reclaimed_ledger_bytes"], 64 * 1024)

    def test_foreign_active_row_and_root_policy_are_unchanged(self):
        ledger, selections, admin = inputs()
        before = copy.deepcopy(ledger)
        result = plan(ledger, selections, admin)["ledger"]
        self.assertEqual(result["reservations"][OTHER], before["reservations"][OTHER])
        self.assertEqual({k: result[k] for k in ("roots", "limit_bytes", "schema")},
                         {k: before[k] for k in ("roots", "limit_bytes", "schema")})
        self.assertEqual(ledger, before)

    def test_foreign_retained_row_and_selected_budget_status_identity_are_unchanged(self):
        ledger, selections, admin = inputs()
        ledger["reservations"][OTHER]["status"] = "retained"
        result = plan(ledger, selections, admin)["ledger"]
        self.assertEqual(result["reservations"][OTHER], ledger["reservations"][OTHER])
        for key, value in ledger["reservations"][ID].items():
            if key != "explicit_reconciliation":
                self.assertEqual(result["reservations"][ID][key], value)

    def test_pure_functions_make_no_file_opens(self):
        ledger, selections, admin = inputs()
        with patch("builtins.open", side_effect=AssertionError("filesystem effect")), patch("os.open", side_effect=AssertionError("filesystem effect")):
            result = plan(ledger, selections, admin)
            sdk.restore_archived_record(result["snapshot_bytes"], result["ledger"]["reservations"][ID])
            sdk.required_peak_bytes(len(result["snapshot_bytes"]), len(result["ledger_bytes"]))

    def test_selected_active_is_refused(self):
        ledger, selections, admin = inputs()
        ledger["reservations"][ID]["status"] = "active"
        with self.assertRaisesRegex(sdk.ArchivalRefusal, "only durable released"):
            plan(ledger, selections, admin)

    def test_selected_retained_is_refused(self):
        ledger, selections, admin = inputs()
        ledger["reservations"][ID]["status"] = "retained"
        with self.assertRaisesRegex(sdk.ArchivalRefusal, "only durable released"):
            plan(ledger, selections, admin)

    def test_missing_durability_is_refused(self):
        ledger, selections, admin = inputs()
        ledger["reservations"][ID]["artifacts_durable_asserted"] = False
        with self.assertRaisesRegex(sdk.ArchivalRefusal, "only durable released"):
            plan(ledger, selections, admin)

    def test_full_record_hash_conflict_is_refused(self):
        ledger, selections, admin = inputs()
        ledger["reservations"][ID]["storage_bytes"] += 1
        with self.assertRaisesRegex(sdk.ArchivalRefusal, "full record hash"):
            plan(ledger, selections, admin)

    def test_reconciliation_hash_conflict_is_refused(self):
        ledger, selections, admin = inputs()
        selections[0]["expected_reconciliation_sha256"] = "0" * 64
        with self.assertRaisesRegex(sdk.ArchivalRefusal, "reconciliation hash"):
            plan(ledger, selections, admin)

    def test_owner_conflict_is_refused(self):
        ledger, selections, admin = inputs()
        selections[0]["expected_owner_pid"] = 999
        with self.assertRaisesRegex(sdk.ArchivalRefusal, "owner identity"):
            plan(ledger, selections, admin)

    def test_attempt_conflict_is_refused(self):
        ledger, selections, admin = inputs()
        selections[0]["expected_attempt_path"] = "/named/foreign-active"
        with self.assertRaisesRegex(sdk.ArchivalRefusal, "attempt identity"):
            plan(ledger, selections, admin)

    def test_duplicate_selection_is_refused(self):
        ledger, selections, admin = inputs()
        with self.assertRaisesRegex(sdk.ArchivalRefusal, "unique reservation"):
            plan(ledger, selections * 2, admin)

    def test_unbounded_selection_is_refused(self):
        with self.assertRaisesRegex(sdk.ArchivalRefusal, "bounded explicit selection"):
            plan(selections=[{}] * 9)

    def test_missing_selected_row_is_refused(self):
        ledger, selections, admin = inputs()
        selections[0]["reservation_id"] = "4" * 32
        with self.assertRaisesRegex(sdk.ArchivalRefusal, "only durable released"):
            plan(ledger, selections, admin)

    def test_already_folded_row_is_refused(self):
        ledger, selections, admin = inputs()
        ledger["reservations"][ID]["explicit_reconciliation"] = {"schema": sdk.POINTER_SCHEMA}
        selections[0]["expected_record_sha256"] = sdk.digest(ledger["reservations"][ID])
        with self.assertRaisesRegex(sdk.ArchivalRefusal, "unarchived explicit"):
            plan(ledger, selections, admin)

    def test_cap_change_is_refused(self):
        ledger, selections, admin = inputs()
        ledger["limit_bytes"] += 1
        with self.assertRaisesRegex(sdk.ArchivalRefusal, "schema and cap"):
            plan(ledger, selections, admin)

    def test_added_top_level_field_is_refused(self):
        ledger, selections, admin = inputs()
        ledger["archive_index"] = {}
        with self.assertRaisesRegex(sdk.ArchivalRefusal, "schema and cap"):
            plan(ledger, selections, admin)

    def test_snapshot_path_traversal_is_refused(self):
        with self.assertRaisesRegex(sdk.ArchivalRefusal, "canonical path"):
            plan(snapshot="/named/private-history/../foreign/snapshot.json")

    def test_small_or_negative_savings_is_refused(self):
        ledger, selections, admin = inputs()
        ledger["reservations"][ID]["explicit_reconciliation"] = {"small": True}
        selections[0]["expected_record_sha256"] = sdk.digest(ledger["reservations"][ID])
        selections[0]["expected_reconciliation_sha256"] = sdk.digest({"small": True})
        with self.assertRaisesRegex(sdk.ArchivalRefusal, "at least64KiB"):
            plan(ledger, selections, admin)

    def test_admin_cannot_overwrite_foreign_row(self):
        ledger, selections, admin = inputs()
        admin["reservation_id"] = OTHER
        with self.assertRaisesRegex(sdk.ArchivalRefusal, "fresh administrative"):
            plan(ledger, selections, admin)

    def test_admin_cannot_be_active_or_fake_parented(self):
        for key, value in (("status", "active"), ("workload", "canonical_parented_phase")):
            ledger, selections, admin = inputs()
            admin[key] = value
            with self.assertRaisesRegex(sdk.ArchivalRefusal, "completed administrative"):
                plan(ledger, selections, admin)

    def test_invalid_admin_native_or_accounting_envelope_is_refused(self):
        for key, value in (("owner_pid", True), ("storage_bytes", 0), ("memory_mb", 0),
                           ("cpu_slots", 0), ("child_process_slots", 0), ("scheduler_lane", "validation"),
                           ("native_lease_id", ""), ("last_usage", None), ("external_charges", {"unowned": 1})):
            ledger, selections, admin = inputs()
            admin[key] = value
            with self.assertRaisesRegex(sdk.ArchivalRefusal, "administrative native/accounting"):
                plan(ledger, selections, admin)

    def test_invalid_admin_attempt_identity_is_refused(self):
        ledger, selections, admin = inputs()
        admin["attempt_directory"] = {"path": "/named/private-history", "device": 1, "inode": 0}
        with self.assertRaisesRegex(sdk.ArchivalRefusal, "administrative attempt identity"):
            plan(ledger, selections, admin)

    def test_snapshot_tampering_is_refused(self):
        result = plan()
        with self.assertRaisesRegex(sdk.ArchivalRefusal, "snapshot content hash"):
            sdk.restore_archived_record(result["snapshot_bytes"] + b" ", result["ledger"]["reservations"][ID])

    def test_pointer_tampering_is_refused(self):
        result = plan()
        folded = copy.deepcopy(result["ledger"]["reservations"][ID])
        folded["explicit_reconciliation"]["original_record_sha256"] = "0" * 64
        with self.assertRaisesRegex(sdk.ArchivalRefusal, "original archived record hash"):
            sdk.restore_archived_record(result["snapshot_bytes"], folded)

    def test_other_record_field_tampering_cannot_be_hidden_by_valid_pointer(self):
        result = plan()
        folded = copy.deepcopy(result["ledger"]["reservations"][ID])
        folded["external_charges"]["preserve-this"] = 0
        with self.assertRaisesRegex(sdk.ArchivalRefusal, "non-reconciliation record fields"):
            sdk.restore_archived_record(result["snapshot_bytes"], folded)

    def test_peak_math_includes_snapshot_atomic_temp_journals_and_directory_margin(self):
        self.assertEqual(sdk.required_peak_bytes(8388608, 8388608), 8388608 * 2 + 2097152 + 65536)
        self.assertLess(sdk.required_peak_bytes(8388608, 8388608), sdk.DEFAULT_PEAK_BYTES)
        for invalid in (0, -1, 8388609, True):
            with self.assertRaisesRegex(sdk.ArchivalRefusal, "bounded archival size"):
                sdk.required_peak_bytes(invalid, 1)


    def test_current_profile_roundtrip_preserves_complete_records(self):
        ledger, selections, admin = current_inputs()
        before = copy.deepcopy(ledger)
        result = current_plan(ledger, selections, admin)
        self.assertEqual(result["snapshot_bytes"], sdk.wire(before))
        self.assertEqual(result["ledger"]["limit_bytes"], 220_000_000_000)
        self.assertEqual(result["ledger"]["reservations"][OTHER], before["reservations"][OTHER])
        self.assertEqual(
            sdk.restore_archived_record(result["snapshot_bytes"], result["ledger"]["reservations"][ID],
                                        profile=sdk.CURRENT_PROFILE),
            before["reservations"][ID],
        )
        self.assertEqual(ledger, before)

    def test_current_reader_accepts_legacy_snapshot_without_rewriting_it(self):
        legacy = plan()
        before = bytes(legacy["snapshot_bytes"])
        restored = sdk.restore_archived_record(before, legacy["ledger"]["reservations"][ID],
                                               profile=sdk.CURRENT_PROFILE)
        self.assertEqual(restored, inputs()[0]["reservations"][ID])
        self.assertEqual(before, legacy["snapshot_bytes"])

    def test_small_current_snapshot_keeps_legacy_pointer_reader_behavior(self):
        result = current_plan()
        folded = result["ledger"]["reservations"][ID]
        self.assertEqual(folded["explicit_reconciliation"]["schema"], sdk.POINTER_SCHEMA)
        self.assertEqual(sdk.restore_archived_record(result["snapshot_bytes"], folded),
                         current_inputs()[0]["reservations"][ID])

    def test_current_large_snapshot_is_explicit_and_legacy_reader_stays_bounded(self):
        ledger, selections, admin = current_inputs()
        record = ledger["reservations"][ID]
        record["explicit_reconciliation"]["proof"] = "p" * (8 * 1024 * 1024)
        selections[0]["expected_record_sha256"] = sdk.digest(record)
        selections[0]["expected_reconciliation_sha256"] = sdk.digest(record["explicit_reconciliation"])
        result = current_plan(ledger, selections, admin)
        self.assertGreater(len(result["snapshot_bytes"]), 8 * 1024 * 1024)
        folded = result["ledger"]["reservations"][ID]
        self.assertEqual(sdk.restore_archived_record(result["snapshot_bytes"], folded,
                                                    profile=sdk.CURRENT_PROFILE), record)
        with self.assertRaisesRegex(sdk.ArchivalRefusal, "bounded original snapshot"):
            sdk.restore_archived_record(result["snapshot_bytes"], folded)

    def test_current_profile_requires_its_exact_cap(self):
        for cap in (160_000_000_000, 220_000_000_001, True):
            with self.subTest(cap=cap):
                ledger, selections, admin = current_inputs()
                ledger["limit_bytes"] = cap
                with self.assertRaisesRegex(sdk.ArchivalRefusal, "schema and cap"):
                    current_plan(ledger, selections, admin)

    def test_current_profile_capacity_and_boundary_keep_exact_arithmetic(self):
        observation = self.capacity()
        for name in ("observed_apparent_bytes", "charged_bytes", "limit_bytes"):
            observation[name] += 60_000_000_000
        self.assertTrue(sdk.check_capacity_precharge(observation, 60, profile=sdk.CURRENT_PROFILE))
        with self.assertRaisesRegex(sdk.ArchivalRefusal, "projection or cap"):
            sdk.check_capacity_precharge(observation, 60)
        observation["observed_apparent_bytes"] += 1
        observation["charged_bytes"] += 1
        with self.assertRaisesRegex(sdk.ArchivalRefusal, "precharge does not fit"):
            sdk.check_capacity_precharge(observation, 60, profile=sdk.CURRENT_PROFILE)

    def test_current_peak_math_preserves_default_and_rejects_invalid_sizes(self):
        bound = 16 * 1024 * 1024
        expected = bound * 2 + 2 * 1024 * 1024 + 65536
        self.assertEqual(sdk.required_peak_bytes(bound, bound, profile=sdk.CURRENT_PROFILE), expected)
        self.assertGreater(expected, sdk.DEFAULT_PEAK_BYTES)
        self.assertEqual(sdk.DEFAULT_PEAK_BYTES, 32 * 1024 * 1024)
        for value in (0, -1, bound + 1, True, 1.0):
            with self.subTest(value=value):
                with self.assertRaisesRegex(sdk.ArchivalRefusal, "bounded archival size"):
                    sdk.required_peak_bytes(value, 1, profile=sdk.CURRENT_PROFILE)

    def test_current_profile_pure_operations_open_no_files(self):
        ledger, selections, admin = current_inputs()
        with patch("builtins.open", side_effect=AssertionError("filesystem effect")), patch(
                "os.open", side_effect=AssertionError("filesystem effect")):
            result = current_plan(ledger, selections, admin)
            sdk.restore_archived_record(result["snapshot_bytes"], result["ledger"]["reservations"][ID],
                                        profile=sdk.CURRENT_PROFILE)
            sdk.required_peak_bytes(len(result["snapshot_bytes"]), len(result["ledger_bytes"]),
                                    profile=sdk.CURRENT_PROFILE)

    def test_unknown_profiles_refuse_before_any_pure_effect(self):
        legacy = plan()
        for profile in (None, True, {}, [], "released-reconciliation-archival/v3"):
            with self.subTest(profile=profile):
                with self.assertRaises(sdk.ArchivalRefusal):
                    sdk.plan_reconciliation_archival(legacy["snapshot_bytes"], selections=inputs()[1],
                        snapshot_path="/named/private-history/ledger-before.private.json",
                        administration_record=inputs()[2], profile=profile)
                with self.assertRaises(sdk.ArchivalRefusal):
                    sdk.restore_archived_record(legacy["snapshot_bytes"],
                        legacy["ledger"]["reservations"][ID], profile=profile)
                with self.assertRaises(sdk.ArchivalRefusal):
                    sdk.required_peak_bytes(1, 1, profile=profile)
                with self.assertRaises(sdk.ArchivalRefusal):
                    sdk.check_capacity_precharge(self.capacity(), 60, profile=profile)


def current_inputs():
    ledger, selections, admin = inputs()
    ledger["limit_bytes"] = 220_000_000_000
    admin["archival"]["schema"] = sdk.CURRENT_PROFILE
    return ledger, selections, admin


def current_plan(ledger=None, selections=None, admin=None):
    fixture = current_inputs()
    return sdk.plan_reconciliation_archival(
        sdk.wire(fixture[0] if ledger is None else ledger),
        selections=fixture[1] if selections is None else selections,
        snapshot_path="/named/private-history/ledger-before.private.json",
        administration_record=fixture[2] if admin is None else admin,
        profile=sdk.CURRENT_PROFILE,
    )


class NativeProfileTests(unittest.TestCase):
    """Explicit private Native fixtures retained for the outer owner's seal."""

    def setUp(self):
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import existing_resource_scheduler
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler
        self.native = resource_scheduler
        self.existing = existing_resource_scheduler
        self.directory = Path(tempfile.mkdtemp(prefix="legal-ir-archive-native-profile-"))
        self.root = self.directory / "outputs"
        self.root.mkdir(mode=0o700)
        self.archive = self.root / "private-history"
        self.archive.mkdir(mode=0o700)
        self.ledger_path = self.directory / "disk.json"
        self.scheduler = self.native.GlobalResourceScheduler(self.native.ResourceSchedulerConfig(
            total_cpu_slots=4, total_memory_mb=4096, total_child_process_slots=8,
            total_gpu_memory_mb=None, total_unified_memory_mb=None,
            lane_reservations={"orchestration": {"cpu_slots": 1, "memory_mb": 0}},
            state_path=self.directory / "native-state.json", proof_safety_enabled=True,
            proof_memory_stall_percent=100.0, proof_cpu_stall_percent=100.0,
            proof_io_stall_percent=100.0, auto_renew_leases=False,
        ))
        self.policy = copy.deepcopy(self._read(self.scheduler.state_path)["config"])
        self.policy_digest = self.existing.policy_sha256(self.policy)
        self.original_caps = (base.MAX_LEDGER_BYTES, base.MAX_STORAGE_BYTES)
        template = inputs()[0]["reservations"][ID]
        rows = {}
        self.selections = []
        for ordinal in range(8):
            identifier = format(0x1000 + ordinal, "032x")
            attempt = self.root / ("old-attempt-" + str(ordinal))
            attempt.mkdir(mode=0o700)
            record = copy.deepcopy(template)
            record.update(reservation_id=identifier, owner_pid=os.getpid(),
                          attempt_directory=base._root_identity(attempt))
            record["explicit_reconciliation"]["ordinal"] = ordinal
            rows[identifier] = record
            self.selections.append({"reservation_id": identifier,
                "expected_record_sha256": sdk.digest(record),
                "expected_reconciliation_sha256": sdk.digest(record["explicit_reconciliation"]),
                "expected_owner_pid": os.getpid(), "expected_attempt_path": str(attempt)})
        foreign = inputs()[0]["reservations"][OTHER]
        for identifier, status in ((OTHER, "active"), ("4" * 32, "retained")):
            attempt = self.root / ("foreign-" + status)
            attempt.mkdir(mode=0o700)
            record = copy.deepcopy(foreign)
            record.update(reservation_id=identifier, status=status, owner_pid=os.getpid(),
                          attempt_directory=base._root_identity(attempt))
            rows[identifier] = record
        self.original = {"schema": base.SCHEMA, "roots": [base._root_identity(self.root)],
                         "limit_bytes": base.MAX_STORAGE_BYTES, "reservations": rows}
        with os.fdopen(os.open(self.ledger_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                               0o600), "wb") as stream:
            stream.write(sdk.wire(self.original))
            stream.flush()
            os.fsync(stream.fileno())

    def tearDown(self):
        self.assertEqual(self.scheduler.snapshot()["allocated"]["cpu_slots"], 0)
        self.assertEqual(self._read(self.scheduler.state_path)["config"], self.policy)
        self.assertEqual((base.MAX_LEDGER_BYTES, base.MAX_STORAGE_BYTES), self.original_caps)

    @staticmethod
    def _read(path):
        return json.loads(path.read_bytes())

    @contextmanager
    def _leases(self):
        with self.scheduler.acquire("orchestration", cpu_slots=1, memory_mb=256,
                child_process_slots=1, timeout=10, request_id="private-archive-test:root") as root:
            with root.acquire_child(cpu_slots=1, memory_mb=256, child_process_slots=1,
                    timeout=10, request_id="private-archive-test:phase") as phase:
                yield root, phase
        self.assertTrue(root.released)
        self.assertTrue(phase.released)

    def _invoke(self, root, phase, **overrides):
        arguments = dict(ledger_path=self.ledger_path, roots=[self.root],
            archive_directory=self.archive, selections=self.selections,
            expected_ledger_sha256=sdk.sha(self.ledger_path.read_bytes()),
            root_lease=root, phase_lease=phase,
            root_request_id="private-archive-test:root", phase_request_id="private-archive-test:phase",
            scheduler_state_path=self.scheduler.state_path,
            expected_scheduler_policy_sha256=self.policy_digest,
            peak_storage_bytes=32 * 1024 * 1024, timeout_seconds=30)
        arguments.update(overrides)
        return sdk.archive_released_reconciliations(**arguments)

    def test_legacy_native_profile_refuses_current_host_before_write(self):
        self.assertEqual(self.original_caps, (16 * 1024 * 1024, 220_000_000_000))
        before = self.ledger_path.read_bytes()
        with self._leases() as (root, phase):
            with self.assertRaisesRegex(sdk.ArchivalRefusal, "unchanged native caps required"):
                self._invoke(root, phase)
            self.assertEqual(self.ledger_path.read_bytes(), before)
            self.assertEqual(tuple(self.archive.iterdir()), ())
            self.assertFalse(root.released)
            self.assertFalse(phase.released)

    def test_current_native_profile_archives_all_eight_and_preserves_foreign_rows(self):
        before = self.ledger_path.read_bytes()
        with self._leases() as (root, phase):
            result = self._invoke(root, phase, profile=sdk.CURRENT_PROFILE)
            self.assertFalse(root.released)
            self.assertFalse(phase.released)
            self.assertEqual(result["schema"], sdk.CURRENT_PROFILE)
            self.assertTrue(result["archive_history_durable"])
            self.assertTrue(result["actual_postwrite_capacity_satisfied"])
            self.assertTrue(result["all_original_selected_records_reconstructed"])
            self.assertFalse(result["active_or_retained_rows_changed"])
            self.assertFalse(result["native_caps_changed"])
            self.assertEqual(result["actual_native_root_id"], root.lease_id)
            self.assertEqual(result["actual_native_phase_id"], phase.lease_id)
        saved = (self.archive / "ledger-before.private.json").read_bytes()
        self.assertEqual(saved, before)
        actual = self._read(self.ledger_path)
        self.assertEqual(actual["roots"], self.original["roots"])
        self.assertEqual(actual["limit_bytes"], self.original["limit_bytes"])
        for selection in self.selections:
            identifier = selection["reservation_id"]
            rebuilt = sdk.restore_archived_record(saved, actual["reservations"][identifier],
                                                  profile=sdk.CURRENT_PROFILE)
            self.assertEqual(rebuilt, self.original["reservations"][identifier])
        for identifier in (OTHER, "4" * 32):
            self.assertEqual(actual["reservations"][identifier], self.original["reservations"][identifier])
        added = set(actual["reservations"]) - set(self.original["reservations"])
        self.assertEqual(len(added), 1)
        admin = actual["reservations"][added.pop()]
        self.assertEqual(admin["status"], "released")
        self.assertEqual(admin["archival"]["schema"], sdk.CURRENT_PROFILE)
        self.assertEqual(admin["storage_bytes"], 32 * 1024 * 1024)
        self.assertEqual(set(path.name for path in self.archive.iterdir()),
                         {"ledger-before.private.json", "admission-intent.private.json"})

    def test_current_native_profile_rejects_unknown_profile_before_write(self):
        before = self.ledger_path.read_bytes()
        with self._leases() as (root, phase):
            with self.assertRaises(sdk.ArchivalRefusal):
                self._invoke(root, phase, profile="released-reconciliation-archival/v3")
        self.assertEqual(self.ledger_path.read_bytes(), before)
        self.assertEqual(tuple(self.archive.iterdir()), ())

    def test_current_native_profile_rejects_ledger_cap_mismatch_before_write(self):
        damaged = copy.deepcopy(self.original)
        damaged["limit_bytes"] = 160_000_000_000
        self.ledger_path.write_bytes(sdk.wire(damaged))
        before = self.ledger_path.read_bytes()
        with self._leases() as (root, phase):
            with self.assertRaises((sdk.ArchivalRefusal, base.DaemonResourceError)):
                self._invoke(root, phase, profile=sdk.CURRENT_PROFILE)
        self.assertEqual(self.ledger_path.read_bytes(), before)
        self.assertEqual(tuple(self.archive.iterdir()), ())

    def test_current_native_profile_rejects_unbound_peak_before_write(self):
        before = self.ledger_path.read_bytes()
        with self._leases() as (root, phase):
            for peak in (32 * 1024 * 1024 - 1, 64 * 1024 * 1024 + 1, True):
                with self.subTest(peak=peak):
                    with self.assertRaises(sdk.ArchivalRefusal):
                        self._invoke(root, phase, profile=sdk.CURRENT_PROFILE, peak_storage_bytes=peak)
        self.assertEqual(self.ledger_path.read_bytes(), before)
        self.assertEqual(tuple(self.archive.iterdir()), ())


    def test_current_native_profile_requires_explicit_peak_for_large_snapshot(self):
        ledger = copy.deepcopy(self.original)
        unselected_id = "5" * 32
        unselected_attempt = self.root / "unselected-large-released"
        unselected_attempt.mkdir(mode=0o700)
        unselected = copy.deepcopy(ledger["reservations"][OTHER])
        unselected.update(reservation_id=unselected_id, status="released",
            artifacts_durable_asserted=True,
            attempt_directory=base._root_identity(unselected_attempt))
        unselected["opaque_authority_free_metadata"]["padding"] = "u" * (15 * 1024**2 - 128 * 1024)
        ledger["reservations"][unselected_id] = unselected
        before = sdk.wire(ledger)
        self.assertGreater(len(before), 15 * 1024**2)
        self.assertLessEqual(len(before), 16 * 1024**2)
        self.ledger_path.write_bytes(before)
        with self._leases() as (root, phase):
            with self.assertRaisesRegex(sdk.ArchivalRefusal, "amplification exceeds precharge"):
                self._invoke(root, phase, profile=sdk.CURRENT_PROFILE)
            self.assertEqual(self.ledger_path.read_bytes(), before)
            self.assertEqual(tuple(self.archive.iterdir()), ())
            self.assertFalse(root.released)
            self.assertFalse(phase.released)
            result = self._invoke(root, phase, profile=sdk.CURRENT_PROFILE,
                                  peak_storage_bytes=64 * 1024**2)
            self.assertTrue(result["archive_history_durable"])
            self.assertTrue(result["all_original_selected_records_reconstructed"])
            self.assertFalse(result["native_caps_changed"])
        snapshot = (self.archive / "ledger-before.private.json").read_bytes()
        self.assertEqual(snapshot, before)
        actual = self._read(self.ledger_path)
        for selection in self.selections:
            identifier = selection["reservation_id"]
            rebuilt = sdk.restore_archived_record(snapshot, actual["reservations"][identifier],
                                                  profile=sdk.CURRENT_PROFILE)
            self.assertEqual(rebuilt, ledger["reservations"][identifier])
        for identifier in (OTHER, "4" * 32, unselected_id):
            self.assertEqual(actual["reservations"][identifier], ledger["reservations"][identifier])
        self.assertEqual(actual["roots"], ledger["roots"])
        self.assertEqual(actual["limit_bytes"], ledger["limit_bytes"])
        added = set(actual["reservations"]) - set(ledger["reservations"])
        self.assertEqual(len(added), 1)
        admin = actual["reservations"][added.pop()]
        self.assertEqual(admin["status"], "released")
        self.assertEqual(admin["storage_bytes"], 64 * 1024**2)



if __name__ == "__main__":
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(MemoryProtocolTests))
    raise SystemExit(0 if result.wasSuccessful() else 1)
