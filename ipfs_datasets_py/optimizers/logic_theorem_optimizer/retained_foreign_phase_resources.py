"""Bounded foreign DuckDB custody in the existing native disk ledger.

The named-root census and ledger format remain unchanged. One real phase
reservation conservatively covers its declared foreign files. When compute
stops, a bounded part of that SAME reservation remains retained while those
files exist; even older producers include it in outstanding storage bytes.
This is cooperative accounting, not a filesystem quota or write permission.
"""
from __future__ import annotations

import copy
import hashlib
import os
from pathlib import Path
import stat
import time

from . import autoencoder_daemon_resources as host
from .parented_phase_resources import ParentedPhaseResourceReservation, _need

SCOPE_SCHEMA = "retained-foreign-duckdb-scope/v1"


def _scope(value, roots, storage_bytes):
    _need(type(value) is dict and set(value) == {
        "schema", "database_path", "parent_identity", "retained_bytes"},
        "foreign scope must be a closed predeclared DuckDB scope")
    _need(value["schema"] == SCOPE_SCHEMA, "foreign scope schema differs")
    path = Path(value["database_path"])
    _need(type(value["database_path"]) is str and path.is_absolute()
          and str(path) == value["database_path"] and path.resolve(strict=False) == path
          and path.suffix == ".duckdb",
          "exact absolute foreign DuckDB path required")
    _need(not any(path == root or root in path.parents for root in roots),
          "foreign scope must be outside the named-root census")
    parent = host._root_identity(path.parent)
    _need(value["parent_identity"] == parent, "foreign parent identity differs")
    host._integer(value["retained_bytes"], "foreign retained bytes", maximum=storage_bytes)
    # Derive the entire finite allowance: arbitrary sibling paths or parent
    # directory inventories cannot be smuggled into this declaration.
    return copy.deepcopy(value), (path, path.with_name(path.name + ".wal"),
                                 path.with_name("." + path.name + ".lock"),
                                 path.with_name("." + path.name + ".serialized-coordinator.lock"))


class RetainedForeignPhaseResourceReservation(ParentedPhaseResourceReservation):
    """One native phase child with persistent, bounded foreign-file custody.

    ``foreign_scope`` is immutable request metadata from the trusted finite
    owner. It names one DuckDB file, its WAL and both native lock files, and
    binds the exact existing parent directory device/inode. The first use must
    see an existing unaliased database. A later phase can transfer only an
    explicitly stopped retained record, under the same existing ledger lock.
    Ordinary context failure retains the full promise and is not transferable.
    """

    def __init__(self, ledger_path, *, foreign_scope, **kwargs):
        self._foreign_scope, self._foreign_paths = _scope(
            foreign_scope, tuple(Path(p).absolute() for p in kwargs["roots"]),
            kwargs["storage_bytes"])
        self._foreign_finalized = False
        self._foreign_predecessor = None
        self._initial_storage_bytes = kwargs["storage_bytes"]
        super().__init__(ledger_path, **kwargs)
        self._sources[Path(__file__)] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        self._foreign_usage()

    def _verify_owner_roots(self):
        super()._verify_owner_roots()
        _need(host._root_identity(self._foreign_paths[0].parent)
              == self._foreign_scope["parent_identity"], "foreign parent identity changed")

    def _foreign_usage(self):
        self._verify_owner_roots()
        allowed = {path.name for path in self._foreign_paths}
        # Refuse an unexpected DuckDB spill/temp/backup belonging to this
        # database; unrelated sibling files are outside this finite scope.
        with os.scandir(self._foreign_paths[0].parent) as entries:
            for index, entry in enumerate(entries):
                _need(index < 4096, "foreign parent entry bound exceeded")
                _need(not entry.name.startswith(self._foreign_paths[0].name + ".")
                      or entry.name in allowed, "undeclared foreign DuckDB companion")
        rows, total = [], 0
        for path in self._foreign_paths:
            host._safe_path(path, missing=True)
            try:
                info = path.lstat()
            except FileNotFoundError:
                rows.append({"path": str(path), "exists": False, "bytes": 0})
                continue
            _need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                  and info.st_uid == os.geteuid(), "foreign file must be regular, owned and unaliased")
            total += info.st_size
            rows.append({"path": str(path), "exists": True, "bytes": info.st_size,
                         "device": info.st_dev, "inode": info.st_ino})
        _need(total <= self._foreign_scope["retained_bytes"], "foreign retained byte limit exceeded")
        self._verify_owner_roots()
        return {"foreign_observed_bytes": total, "foreign_files": rows,
                "foreign_retained_limit_bytes": self._foreign_scope["retained_bytes"]}

    def _validate_new_reservation(self, ledger):
        super()._validate_new_reservation(ledger)
        previous = []
        active = {row["lease_id"] for row in self._admission.active_leases()}
        for key, row in ledger["reservations"].items():
            metadata = row.get("foreign_scope")
            if not isinstance(metadata, dict) or row["status"] == "released":
                continue
            declaration = metadata.get("declaration", {})
            if declaration.get("database_path") != self._foreign_scope["database_path"]:
                continue
            _need(declaration == self._foreign_scope, "foreign scope declaration changed")
            _need(row["status"] == "retained" and metadata.get("custody_state") == "retained_stopped"
                  and row.get("artifacts_durable_asserted") is True
                  and metadata.get("native_child_released_after_stop") is True
                  and row.get("native_lease_id") not in active
                  and not host._group_usage(row.get("child"))["live_processes"],
                  "foreign scope has an outstanding or interrupted owner")
            _need(row["storage_bytes"] == self._foreign_scope["retained_bytes"],
                  "retained foreign promise differs")
            previous.append(key)
        _need(len(previous) <= 1, "foreign scope has duplicate retained custodians")
        _need(previous or self._foreign_paths[0].exists(),
              "first foreign scope admission requires an existing database")
        self._foreign_predecessor = previous[0] if previous else None

    def _write(self, value):
        row = value["reservations"].get(self.reservation_id)
        if row is not None and "foreign_scope" not in row:
            row["foreign_scope"] = {"declaration": copy.deepcopy(self._foreign_scope),
                                    "custody_state": "active",
                                    "initial_storage_bytes": self._initial_storage_bytes,
                                    "predecessor_reservation_id": self._foreign_predecessor}
        if row is not None and row["status"] == "released":
            _need(not any(item["exists"] for item in self._foreign_usage()["foreign_files"]),
                  "foreign artifacts remain at disk release")
            row["foreign_scope"]["custody_state"] = "released_empty"
        super()._write(value)

    def __enter__(self):
        super().__enter__()
        try:
            if self._foreign_predecessor is not None:
                with self._locked():
                    ledger = self._read()
                    predecessor = ledger["reservations"][self._foreign_predecessor]
                    _need(predecessor["status"] == "retained"
                          and predecessor["foreign_scope"]["custody_state"] == "retained_stopped"
                          and predecessor["foreign_scope"]["native_child_released_after_stop"] is True,
                          "foreign predecessor changed before transfer")
                    # Both full promises were charged at admission. Transfer
                    # only after the new real native child is alive.
                    predecessor["status"] = "released"
                    predecessor["released_at"] = time.time()
                    predecessor["foreign_scope"].update(custody_state="transferred",
                        successor_reservation_id=self.reservation_id)
                    self._account(ledger)
                    self._write(ledger)
        except BaseException:
            import sys
            self.__exit__(*sys.exc_info())
            raise
        return self

    def check_usage(self, attempt_directory, child_pid=None, *, full=False):
        usage = super().check_usage(attempt_directory, child_pid=child_pid, full=full)
        foreign = self._foreign_usage()
        combined = usage["total_attempt_charged_bytes"] + foreign["foreign_observed_bytes"]
        _need(combined <= self.storage_bytes, "attempt and foreign storage byte limit exceeded")
        usage.update(foreign, total_attempt_and_foreign_bytes=combined)
        self._last_local_usage = copy.deepcopy(usage)
        return usage

    def finalize(self, attempt_directory, *, artifacts_durable=False):
        if self._foreign_finalized:
            return self.to_dict()
        _need(artifacts_durable is True, "explicit artifact durability assertion required")
        _need(host._safe_path(attempt_directory, directory=True) == self.directory,
              "phase attempt directory differs")
        _need(not self._native_consumers(), "native consumers must finish before foreign custody retention")
        _need(not host._group_usage(self._child)["live_processes"], "child process group is still alive")
        if (self._record is not None and self._record["status"] == "retained"
                and self._record["foreign_scope"]["custody_state"] == "retained_stopped"):
            return self._finish_compute_stop()
        usage = self.check_usage(attempt_directory, full=True)
        self._closing_mode = "productive"
        try:
            with self._locked():
                ledger = self._read()
                row = ledger["reservations"][self.reservation_id]
                # Check fresh foreign bytes inside the same accounting lock.
                foreign = self._foreign_usage()
                accounting = self._account(ledger)
                row.update(status="retained", storage_bytes=self._foreign_scope["retained_bytes"],
                    retention_reason="bounded_foreign_artifacts_persist", artifacts_durable_asserted=True,
                    foreign_compute_stopped_at=time.time(), final_attempt_bytes=usage["attempt_bytes"],
                    final_external_charged_bytes=usage["external_charged_bytes"],
                    final_external_charges=copy.deepcopy(row.get("external_charges", {})),
                    external_charges={})
                row["foreign_scope"].update(custody_state="retained_stopped", **foreign)
                row["final_accounting"] = {**accounting,
                    "outstanding_full_reservations_bytes": accounting["outstanding_full_reservations_bytes"]
                        - self.storage_bytes + row["storage_bytes"],
                    "charged_bytes": accounting["charged_bytes"] - self.storage_bytes + row["storage_bytes"]}
                self._write(ledger)
                self._record = copy.deepcopy(row)
        finally:
            self._closing_mode = None
        return self._finish_compute_stop()

    def _finish_compute_stop(self):
        # Original native capability release precedes its durable observation;
        # absence, age, PID death or a copied receipt cannot replace this call.
        self._lease.release()
        self._closing_mode = "cleanup"
        try:
            with self._locked():
                ledger = self._read()
                row = ledger["reservations"][self.reservation_id]
                row["foreign_scope"]["native_child_released_after_stop"] = True
                self._write(ledger)
                self._record = copy.deepcopy(row)
            self._foreign_finalized = True
        finally:
            self._closing_mode = None
        return self.to_dict()

    def release(self, *, artifacts_durable=False):
        """Release disk custody only when every declared foreign file is gone."""
        if self._foreign_finalized and self._record["status"] == "released":
            return self.to_dict()
        _need(not any(row["exists"] for row in self._foreign_usage()["foreign_files"]),
              "foreign artifacts persist; finalize must retain their promise")
        _need(not self._foreign_finalized,
              "retained stopped custody requires a fresh native phase for empty-scope retirement")
        super().finalize(self.directory, artifacts_durable=artifacts_durable)
        # Complete original capability release even after a genuine response
        # loss at the base finalizer's already-committed disk-release boundary.
        self._lease.release()
        self._foreign_finalized = True
        return self.to_dict()

    close = release

    def to_dict(self):
        result = super().to_dict()
        result.update(profile="native_phase_with_bounded_retained_foreign_duckdb_custody/v1",
                      foreign_file_growth_monitored=True,
                      foreign_growth_monitoring_scope="exact_declared_database_wal_and_two_native_locks",
                      foreign_compute_finalized=self._foreign_finalized,
                      disk_custody_released=(self._record is not None
                                             and self._record["status"] == "released"))
        return result

    def __exit__(self, exc_type, exc, traceback):
        if self._foreign_finalized:
            return False
        return super().__exit__(exc_type, exc, traceback)
