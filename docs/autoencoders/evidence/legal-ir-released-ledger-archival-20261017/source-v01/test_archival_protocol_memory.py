"""Effect-free unittest controls. They do not qualify native/storage effects.

Run only under root's genuine finite scheduler root/phase admission, with
python -I -S -B. No pytest, temp files, caches, JUnit or test artifacts are used.
"""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("authored_ledger_archival", Path(__file__).with_name("autoencoder_ledger_archival.py"))
sdk = importlib.util.module_from_spec(spec)
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


if __name__ == "__main__":
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(MemoryProtocolTests))
    raise SystemExit(0 if result.wasSuccessful() else 1)
