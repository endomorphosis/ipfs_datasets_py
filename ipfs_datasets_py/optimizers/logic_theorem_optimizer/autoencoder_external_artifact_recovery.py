"""Explicit recovery of one dead owner's retained claim with one external tree.

This separate API never admits work, deletes outputs, expires claims by age or
changes capacity. Its caller must independently own native/source custody.
The existing recovery API and its refusal of external charges are unchanged.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as resources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_resource_recovery as legacy


class ExternalRecoveryWriteIncomplete(resources.DaemonResourceError):
    """A write/verification failed; disposition comes only from locked readback.

    ``postwrite_verification_pending`` describes the unresolved operation, not
    the observed ledger marker. Even an exact final receipt observed after a
    write error does not establish that failed write's durability.
    """

    def __init__(self, reservation_id, *, stage, observation,
                 initial_release_write_completed, receipt_write_completed):
        super().__init__("external recovery incomplete; explicit readback disposition required")
        self.reservation_id = reservation_id
        self.stage = stage
        self.observation = copy.deepcopy(observation)
        self.claim_released = observation["claim_released"]
        self.observed_disposition = observation["disposition"]
        self.ledger_postwrite_verification_pending = observation["ledger_postwrite_verification_pending"]
        self.ledger_actual_postwrite_census_verified = observation["ledger_actual_postwrite_census_verified"]
        self.postwrite_verification_pending = True
        self.initial_release_write_completed = initial_release_write_completed
        self.receipt_write_completed = receipt_write_completed
        self.observed_record_durability_verified = (
            observation["disposition"] == "released_pending_observed" and initial_release_write_completed
            or observation["disposition"] == "released_receipt_observed" and receipt_write_completed)
        self.automatic_retry_permitted = False
        self.rollback_claimed = False


class ExternalRecoveryPostwritePending(ExternalRecoveryWriteIncomplete):
    """The initial write returned, but subsequent verification did not finish."""


def _need(value, message):
    if not value:
        raise resources.DaemonResourceError(message)


def _proof_bytes(pin):
    _need(type(pin) is dict and set(pin) == {"path", "bytes", "sha256"},
          "external recovery proof pin is not closed")
    _need(type(pin["bytes"]) is int and 0 <= pin["bytes"] <= 8 * 1024**2
          and type(pin["sha256"]) is str and re.fullmatch("[0-9a-f]{64}", pin["sha256"]),
          "external recovery proof pin is invalid")
    path = resources._safe_path(pin["path"])
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        before = os.fstat(descriptor)
        _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
              and before.st_size == pin["bytes"], "external recovery proof file differs")
        raw = bytearray()
        while len(raw) <= pin["bytes"]:
            block = os.read(descriptor, min(65536, pin["bytes"] + 1 - len(raw)))
            if not block:
                break
            raw.extend(block)
        after = os.fstat(descriptor)
        fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
        identity = lambda value: tuple(getattr(value, field) for field in fields)
        _need(len(raw) == pin["bytes"] and hashlib.sha256(raw).hexdigest() == pin["sha256"]
              and identity(before) == identity(after) == identity(path.lstat()),
              "external recovery proof changed")
        return bytes(raw)
    finally:
        os.close(descriptor)


def _artifact_list(value):
    _need(type(value) is list and 1 <= len(value) <= 16000,
          "external recovery requires a nonempty bounded artifact inventory")
    paths = []
    for row in value:
        _need(type(row) is dict and set(row) == {"path", "bytes", "sha256"},
              "external recovery artifact row is not closed")
        _need(type(row["path"]) is str and row["path"], "external recovery artifact path is invalid")
        path = Path(row["path"])
        _need(not path.is_absolute()
              and ".." not in path.parts and str(path) == row["path"]
              and type(row["bytes"]) is int and row["bytes"] >= 0
              and type(row["sha256"]) is str and re.fullmatch("[0-9a-f]{64}", row["sha256"]),
              "external recovery artifact row is invalid")
        paths.append(row["path"])
    # Match the unchanged durable producer's component-wise Path ordering.
    # Validate the supplied inventory verbatim; never reorder its evidence.
    _need(paths == sorted(set(paths), key=Path), "external recovery artifact paths repeat or are unsorted")
    return value


def reconcile_retained_external_reservation(ledger_path, *, roots, reservation_id,
        expected_record_sha256, attempt_directory, expected_artifacts,
        external_evidence, artifacts_durable=False, capacity_policy="require_capacity"):
    """Release one exact retained claim after both trees are durable and stopped.

    ``external_evidence`` is a closed record binding the one original charge to
    its original execution-request metadata, exact current root identity and
    complete expected file inventory. Both trees must be disjoint and already
    inside the ledger's named roots, where their real bytes remain counted.
    All original external-charge metadata stays intact. An explicit
    administrative closeout may record an existing overage, never admit work.

    Release is marked postwrite-pending first. Success requires both a real
    subsequent census/readback and a final nonpersisted census/readback after
    receipt persistence. Any write error is classified by actual locked
    readback as retained, released/pending, released/receipt or unknown; no
    exception invents rollback, durability or an automatic retry permission.
    """
    _need(type(capacity_policy) is str and capacity_policy in {
        "require_capacity", "administrative_closeout"}, "invalid external recovery capacity policy")
    _need(artifacts_durable is True, "explicit attempt durability assertion required")
    _artifact_list(expected_artifacts)
    expected_artifacts = copy.deepcopy(expected_artifacts)
    keys = {"charge_key", "charged_bytes", "root_identity", "execution_request_pin",
            "expected_artifacts", "artifacts_durable"}
    _need(type(external_evidence) is dict and set(external_evidence) == keys
          and external_evidence["artifacts_durable"] is True,
          "external recovery evidence is not a closed durable scope")
    evidence = copy.deepcopy(external_evidence)
    _artifact_list(evidence["expected_artifacts"])
    charge_key, charge = evidence["charge_key"], evidence["charged_bytes"]
    _need(type(charge_key) is str and resources._CHARGE_KEY.fullmatch(charge_key)
          and type(charge) is int and charge > 0, "external recovery charge is invalid")
    identity = evidence["root_identity"]
    _need(type(identity) is dict and set(identity) == {"path", "device", "inode"}
          and type(identity["path"]) is str
          and type(identity["device"]) is int and type(identity["inode"]) is int,
          "external recovery root identity is not closed")
    helper = resources.DaemonResourceReservation(ledger_path, roots=roots,
        storage_bytes=1, memory_mb=1, ledger_lock_timeout_seconds=30,
        require_existing_ledger=True)
    attempt = resources._safe_path(attempt_directory, directory=True)
    external = resources._safe_path(identity["path"], directory=True)
    _need(all(any(path == root or root in path.parents for root in helper.roots)
              for path in (attempt, external)), "recovery tree is outside named storage roots")
    _need(attempt != external and attempt not in external.parents and external not in attempt.parents,
          "external and attempt recovery trees overlap")
    _need(resources._root_identity(external) == identity, "external recovery root identity changed")
    proof_pin = evidence["execution_request_pin"]
    _need(type(proof_pin) is dict and proof_pin.get("path") == str(attempt / "execution-request.json"),
          "external recovery proof is not the original attempt execution request")
    proof_raw = _proof_bytes(proof_pin)
    proof = json.loads(proof_raw, object_pairs_hook=resources._json_pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(resources.DaemonResourceError("nonfinite execution request")))
    _need(type(proof) is dict and proof.get("disk_reservation_id") == reservation_id
          and proof.get("external_precharge") == {"root": str(external), "bytes": charge},
          "external recovery path or charge differs from original execution request")

    with helper._locked():
        ledger = helper._read()
        record = ledger["reservations"].get(reservation_id)
        _need(record is not None and record["status"] == "retained"
              and legacy._digest(record) == expected_record_sha256,
              "retained external reservation identity changed")
        original_charges = copy.deepcopy(resources._external_charges(record))
        _need(original_charges == {charge_key: charge}, "original external charge map differs")
        _need(record.get("attempt_directory") == resources._root_identity(attempt),
              "recovery attempt identity changed")
        _need(charge <= record["storage_bytes"], "external allowance exceeds original reservation")
        original_identity = copy.deepcopy(record["attempt_directory"])
        other_sha = legacy._digest({key: row for key, row in ledger["reservations"].items()
                                   if key != reservation_id})

        def stopped():
            _need(resources._process(record["owner_pid"]) is None,
                  "original external reservation owner PID still exists")
            for child in (record.get("child"), *record.get("prior_children", ())):
                _need(resources._group_usage(child)["live_processes"] == 0,
                      "retained external child group is still alive")

        def inventories():
            _need(resources._root_identity(attempt) == original_identity
                  and resources._root_identity(external) == identity,
                  "external recovery tree identity changed")
            actual_attempt = legacy._durable_inventory(attempt)
            actual_external = legacy._durable_inventory(external)
            _need(actual_attempt == expected_artifacts
                  and actual_external == evidence["expected_artifacts"],
                  "durable external recovery artifact inventory differs")
            _need(_proof_bytes(proof_pin) == proof_raw, "original execution request changed")
            return actual_attempt, actual_external

        def unchanged():
            _need(legacy._digest(record) == expected_record_sha256
                  and legacy._digest({key: row for key, row in ledger["reservations"].items()
                                      if key != reservation_id}) == other_sha,
                  "external recovery ledger selection changed")

        stopped()
        attempt_inventory, external_inventory = inventories()
        attempt_bytes = sum(row["bytes"] for row in attempt_inventory)
        external_bytes = sum(row["bytes"] for row in external_inventory)
        _need(external_bytes <= charge, "external durable outputs exceed original allowance")
        _need(attempt_bytes + charge <= record["storage_bytes"],
              "attempt plus external allowance exceeds original reservation")
        before = (legacy._administrative_census(helper, ledger) if capacity_policy == "administrative_closeout"
                  else helper._account(ledger))
        unchanged(); stopped(); inventories()
        projected = copy.deepcopy(ledger)
        projected["reservations"][reservation_id]["status"] = "released"
        projected_accounting = legacy._administrative_census(helper, projected)
        if capacity_policy == "require_capacity":
            _need(projected_accounting["capacity_satisfied"] is True,
                  "external recovery prewrite capacity changed")
        _need(before["outstanding_full_reservations_bytes"]
              - projected_accounting["outstanding_full_reservations_bytes"] == record["storage_bytes"],
              "external recovery projection releases a different claim")
        unchanged(); stopped(); inventories()
        recovery = {"schema": "explicit-retained-external-reservation-reconciliation/v1",
            "reservation_id": reservation_id, "previous_record_sha256": expected_record_sha256,
            "original_owner_pid": record["owner_pid"], "reconciled_by_pid": os.getpid(),
            "other_reservations_sha256": other_sha, "capacity_policy": capacity_policy,
            "artifacts": attempt_inventory, "external_root_identity": identity,
            "external_artifacts": external_inventory, "execution_request_pin": proof_pin,
            "original_external_charges": original_charges, "external_actual_bytes": external_bytes,
            "full_claim_accounting": before, "projected_final_accounting": projected_accounting,
            "actual_postwrite_census_verified": False, "postwrite_verification_pending": True,
            "outputs_deleted": False, "automatic_expiry": False, "admitted": False,
            "cap_changed": False, "new_reservation_created": False, "new_resource_lease_acquired": False}
        record.update(status="released", artifacts_durable_asserted=True, released_at=time.time(),
            final_accounting=projected_accounting, final_attempt_bytes=attempt_bytes,
            final_external_charged_bytes=charge, final_total_charged_bytes=attempt_bytes + charge,
            attempt_exceeded_reservation=False, explicit_external_reconciliation=recovery)
        _need(resources._external_charges(record) == original_charges,
              "original external charge history changed")
        pending_sha = legacy._digest(record)
        known_released = {pending_sha: "released_pending_observed"}
        initial_release_write_completed = False
        receipt_write_completed = False

        def observe_disposition():
            # This is the actual on-disk ledger under the same held lock, not
            # the mutated in-memory candidate. An unavailable/mismatched
            # readback never grants a released or retained disposition.
            observation = {"disposition": "unknown", "claim_released": None,
                "readback_succeeded": False, "other_reservations_match": None,
                "selected_record_sha256": None,
                "ledger_postwrite_verification_pending": None,
                "ledger_actual_postwrite_census_verified": None}
            try:
                visible = helper._read()
                observed = visible["reservations"].get(reservation_id)
                observation["readback_succeeded"] = True
                observation["other_reservations_match"] = legacy._digest({
                    key: row for key, row in visible["reservations"].items()
                    if key != reservation_id}) == other_sha
                if observed is None:
                    return observation
                observed_sha = legacy._digest(observed)
                observation["selected_record_sha256"] = observed_sha
                if observation["other_reservations_match"] is not True:
                    return observation
                if observed_sha == expected_record_sha256 and observed["status"] == "retained":
                    observation.update(disposition="retained_preimage_observed", claim_released=False)
                elif observed_sha in known_released and observed["status"] == "released":
                    marker = observed["explicit_external_reconciliation"]
                    observation.update(disposition=known_released[observed_sha], claim_released=True,
                        ledger_postwrite_verification_pending=marker["postwrite_verification_pending"],
                        ledger_actual_postwrite_census_verified=marker["actual_postwrite_census_verified"])
            except BaseException:
                # The outer exception retains the original failure as its
                # cause. Failed readback is explicitly unknown, never rollback.
                pass
            return observation

        def incomplete(error_type, stage):
            return error_type(reservation_id, stage=stage, observation=observe_disposition(),
                initial_release_write_completed=initial_release_write_completed,
                receipt_write_completed=receipt_write_completed)

        try:
            helper._write(ledger)
            initial_release_write_completed = True
        except BaseException as error:
            raise incomplete(ExternalRecoveryWriteIncomplete, "initial_release_write") from error
        stage = "actual_postwrite_verification"
        try:
            written = helper._read()
            _need(legacy._digest(written["reservations"][reservation_id]) == pending_sha
                  and legacy._digest({key: row for key, row in written["reservations"].items()
                                      if key != reservation_id}) == other_sha,
                  "external recovery actual postwrite ledger differs")
            stopped(); inventories()
            postwrite = legacy._administrative_census(helper, written)
            if capacity_policy == "require_capacity":
                _need(postwrite["capacity_satisfied"] is True,
                      "external recovery actual postwrite capacity changed")
            _need(before["outstanding_full_reservations_bytes"]
                  - postwrite["outstanding_full_reservations_bytes"] == record["storage_bytes"],
                  "external recovery actual postwrite claim accounting differs")
            stopped(); inventories()
            recovery.update(actual_postwrite_census_verified=True, postwrite_verification_pending=False,
                actual_postwrite_accounting=postwrite,
                actual_postwrite_census_precedes_receipt_persistence=True,
                returned_final_census_requires_independent_return_evidence=True)
            record["final_accounting"] = postwrite
            record["explicit_external_reconciliation"] = recovery
            _need(legacy._digest({key: row for key, row in ledger["reservations"].items()
                                 if key != reservation_id}) == other_sha,
                  "another reservation changed before recovery receipt persistence")
            receipt_sha = legacy._digest(record)
            known_released[receipt_sha] = "released_receipt_observed"
            stage = "receipt_write"
            helper._write(ledger)
            receipt_write_completed = True
            stage = "final_nonpersisted_census_readback"
            final = helper._read()
            _need(legacy._digest(final["reservations"][reservation_id]) == receipt_sha
                  and legacy._digest({key: row for key, row in final["reservations"].items()
                                      if key != reservation_id}) == other_sha,
                  "external recovery final receipt readback differs")
            stopped(); inventories()
            final_accounting = legacy._administrative_census(helper, final)
            if capacity_policy == "require_capacity":
                _need(final_accounting["capacity_satisfied"] is True,
                      "external recovery final nonpersisted capacity changed")
            _need(before["outstanding_full_reservations_bytes"]
                  - final_accounting["outstanding_full_reservations_bytes"] == record["storage_bytes"],
                  "external recovery final claim accounting differs")
            stopped(); inventories()
            actual_final = helper._read()
            _need(legacy._digest(actual_final["reservations"][reservation_id]) == receipt_sha
                  and legacy._digest({key: row for key, row in actual_final["reservations"].items()
                                      if key != reservation_id}) == other_sha,
                  "external recovery final nonpersisted readback differs")
        except BaseException as error:
            raise incomplete(ExternalRecoveryPostwritePending, stage) from error
        report = copy.deepcopy(recovery)
        report.update(final_nonpersisted_census_verified=True,
            final_nonpersisted_accounting=final_accounting,
            final_nonpersisted_selected_record_sha256=receipt_sha,
            final_nonpersisted_other_reservations_sha256=other_sha,
            final_nonpersisted_evidence_in_ledger=False)
        return report
