"""Explicit bounded, exclusively owned storage for *raw* analysis facts.

This module grants no semantic reconstruction, task, or completion authority.
The existing in-memory scanner and its limits are unchanged.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat

from ..content import canonical_dag_json_bytes, cid_for_structured, validate_cid
from .snapshot import SnapshotError

FRAME_BYTES = 1024 * 1024
WORKING_BYTES = 32 * FRAME_BYTES
PROFILE_SCHEMA = "ipfs-datasets.raw-fact-paging-profile@1"
INDEX_SCHEMA = "ipfs-datasets.raw-fact-index-page@1"


class PagedFactError(SnapshotError):
    def __init__(self, code, *, stage="admission", path=None, limit=None, observed=None, progress=None):
        super().__init__("paged raw facts refused: " + code)
        self.code, self.stage, self.path = code, stage, path
        self.limit, self.observed, self.progress = limit, observed, dict(progress or {})

    def observation(self):
        path = self.path
        details = {}
        if type(path) is str and len(path) > 2048:
            details = {"raw_path_hex_sha256": hashlib.sha256(path.encode()).hexdigest(),
                       "raw_path_hex_length": len(path), "raw_path_hex_prefix": path[:2048]}
            path = None
        progress = {**self.progress, **details}
        if type(progress.get("raw_path_hex")) is str and len(progress["raw_path_hex"]) > 2048:
            progress["raw_path_hex"] = None
        return {"schema": "ipfs-datasets.raw-fact-refusal@1", "code": self.code,
                "stage": self.stage, "raw_path_hex": path, "limit": self.limit,
                "observed": self.observed, "progress": progress,
                "complete_raw_coverage": False, "semantic_reconstruction": False,
                "complete_analysis_authority": False, "completion_authority": False}


def _integer(value, name, ceiling, minimum=1):
    if type(value) is not int or not minimum <= value <= ceiling:
        raise PagedFactError("invalid_" + name)
    return value


def _closed(value, fields, schema=None):
    if type(value) is not dict or set(value) != set(fields) or (schema and value.get("schema") != schema):
        raise PagedFactError("closed_schema", stage="verification")
    return value


def _cid(value):
    if type(value) is not str or len(value) > 128:
        raise PagedFactError("invalid_cid", stage="verification")
    try:
        return validate_cid(value, codecs={"dag-json"})
    except (TypeError, ValueError) as exc:
        raise PagedFactError("invalid_cid", stage="verification") from exc


def _bounded_wire(value, bound):
    """Bound serialization input before allocating its canonical encoding.

    Walk one iterator per nesting level, not an expanded list of all children.
    String escaping can expand the admitted lower bound by at most six; the
    exact canonical result is then checked against the original frame limit.
    """
    pending = [iter((value,))]
    minimum = 0
    while pending:
        item = next(pending[-1], ...)
        if item is ...:
            pending.pop()
            continue
        kind = type(item)
        if kind is dict:
            minimum += 2 + len(item) + max(0, len(item) - 1)
            def entries(mapping):
                for key, part in mapping.items():
                    if type(key) is not str:
                        raise PagedFactError("fact_map_key", stage="storage")
                    yield key
                    yield part
            pending.append(entries(item))
        elif kind is list:
            minimum += 2 + max(0, len(item) - 1)
            pending.append(iter(item))
        elif kind is str:
            minimum += len(item) + 2
        elif kind is int:
            minimum += 1 + (item.bit_length() // 4)
        elif item is None or kind is bool:
            minimum += 4
        else:
            raise PagedFactError("fact_value_type", stage="storage")
        if minimum > bound:
            raise PagedFactError("fact_frame", stage="storage", limit=bound, observed=minimum)
        if len(pending) > 512:
            raise PagedFactError("fact_structure_depth", stage="storage", limit=512)
    wire = canonical_dag_json_bytes(value)
    if not wire or len(wire) > bound:
        raise PagedFactError("fact_frame", stage="storage", limit=bound, observed=len(wire))
    return wire


@dataclass(frozen=True)
class PagedFactProfile:
    """One exact algorithm profile; smaller caller budgets are separate."""
    working_bytes: int = WORKING_BYTES
    frame_bytes: int = FRAME_BYTES
    page_items: int = 256
    max_depth: int = 8

    def __post_init__(self):
        if any(type(value) is not int or value != expected for value, expected in
               zip(asdict(self).values(), (WORKING_BYTES, FRAME_BYTES, 256, 8))):
            raise PagedFactError("unsupported_paging_profile")

    def payload(self):
        self.__post_init__()
        return {"schema": PROFILE_SCHEMA, **asdict(self), "coverage_reference_bytes": WORKING_BYTES // 4,
                "max_structured_depth": 512,
                "analysis_stage": "raw-per-file-only",
                "semantic_reconstruction": False, "completion_authority": False}


@dataclass(frozen=True)
class FactSpoolBudget:
    """Explicit finite cumulative allowances, never inferred from a manifest."""
    max_stored_bytes: int
    max_blocks: int
    max_records: int
    max_io_bytes: int
    max_work_items: int

    def __post_init__(self):
        for name, ceiling in (("max_stored_bytes", 256 * FRAME_BYTES), ("max_blocks", 100_000),
                              ("max_records", 1_000_000), ("max_io_bytes", 4096 * FRAME_BYTES),
                              ("max_work_items", 10_000_000)):
            _integer(getattr(self, name), name, ceiling)


def admit_paging(profile, budget):
    if type(profile) is not PagedFactProfile or type(budget) is not FactSpoolBudget:
        raise PagedFactError("typed_profile_and_budget_required")
    profile.__post_init__()
    budget.__post_init__()


class OwnedFactStore:
    """Cold, single-owner CAS. Existing directories and resumed claims refuse.

    File descriptors retain the exact new directory and lifetime flock. No
    method recursively deletes a directory or exposes an all-blocks mapping.
    Failed reservations remain charged conservatively for this operation.
    """
    def __init__(self, path, *, profile, budget):
        admit_paging(profile, budget)
        self.profile, self.budget = profile, budget
        self._profile_wire = canonical_dag_json_bytes(profile.payload())
        self._budget_wire = canonical_dag_json_bytes(asdict(budget))
        self.path = Path(path).absolute()
        parent = self.path.parent.resolve(strict=True)
        self.path = parent / self.path.name
        if self.path.name in {"", ".", ".."}:
            raise PagedFactError("unsafe_store_path")
        self._fd = self._lease = None
        self._readonly = False
        self._request = self._published = None
        self._used = dict(stored_bytes=0, blocks=0, records=0, io_bytes=0, work_items=0)
        os.mkdir(self.path, 0o700)  # never adopt somebody else's spool
        try:
            self._fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            self._identity = self._directory_identity(os.fstat(self._fd))
            self._lease = os.open("owner.lock", os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                  0o600, dir_fd=self._fd)
            fcntl.flock(self._lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._charge("blocks", 1)
            os.fsync(self._fd)
        except BaseException:
            self.close()
            raise

    @classmethod
    def open_published(cls, path, *, expected_request_cid, expected_root_cid, profile, budget):
        """Reopen exact published raw facts under a shared lifetime lock.

        This reads only; an absent/partial publication cannot be resumed or
        promoted. The caller must still verify the entire coverage DAG.
        """
        admit_paging(profile, budget)
        _cid(expected_request_cid)
        _cid(expected_root_cid)
        self = cls.__new__(cls)
        self.profile, self.budget = profile, budget
        self._profile_wire = canonical_dag_json_bytes(profile.payload())
        self._budget_wire = canonical_dag_json_bytes(asdict(budget))
        self.path = Path(path).absolute()
        self._fd = self._lease = None
        self._readonly = True
        self._request, self._published = expected_request_cid, expected_root_cid
        self._used = dict(stored_bytes=0, blocks=0, records=0, io_bytes=0, work_items=0)
        try:
            self._fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            self._identity = self._directory_identity(os.fstat(self._fd))
            self._lease = os.open("owner.lock", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self._fd)
            lease = os.fstat(self._lease)
            if not stat.S_ISREG(lease.st_mode) or lease.st_uid != os.geteuid() or lease.st_nlink != 1:
                raise PagedFactError("store_lease_shape", stage="verification")
            fcntl.flock(self._lease, fcntl.LOCK_SH | fcntl.LOCK_NB)
            request = self._read_json("request.json", expected_request_cid)
            if request.get("paging_profile") != profile.payload() or request.get("spool_budget") != asdict(budget):
                raise PagedFactError("published_admission_changed", stage="verification")
            marker = _closed(self._read_json("raw-coverage.json"),
                {"schema", "request_cid", "root_cid", "semantic_reconstruction", "completion_authority"},
                "ipfs-datasets.raw-fact-publication@1")
            if (marker["request_cid"] != expected_request_cid or marker["root_cid"] != expected_root_cid or
                    marker["semantic_reconstruction"] is not False or marker["completion_authority"] is not False):
                raise PagedFactError("publication_binding", stage="verification")
            self.get(expected_root_cid)
            return self
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _directory_identity(st):
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid():
            raise PagedFactError("store_directory_identity", stage="storage")
        return st.st_dev, st.st_ino, st.st_uid

    def check(self):
        admit_paging(self.profile, self.budget)
        if (canonical_dag_json_bytes(self.profile.payload()) != self._profile_wire or
                canonical_dag_json_bytes(asdict(self.budget)) != self._budget_wire):
            raise PagedFactError("store_admission_changed", stage="storage")
        if self._fd is None or self._lease is None:
            raise PagedFactError("store_closed", stage="storage")
        try:
            if (self._directory_identity(os.fstat(self._fd)) != self._identity or
                    self._directory_identity(self.path.lstat()) != self._identity):
                raise PagedFactError("store_directory_changed", stage="storage")
            lease = os.fstat(self._lease)
            named = os.stat("owner.lock", dir_fd=self._fd, follow_symlinks=False)
            if (not stat.S_ISREG(lease.st_mode) or lease.st_uid != os.geteuid() or lease.st_nlink != 1 or
                    not stat.S_ISREG(named.st_mode) or (lease.st_dev, lease.st_ino) != (named.st_dev, named.st_ino)):
                raise PagedFactError("store_lease_changed", stage="storage")
        except OSError as exc:
            raise PagedFactError("store_identity_unavailable", stage="storage") from exc

    def _charge(self, name, amount):
        _integer(amount, "charge", 4096 * FRAME_BYTES, minimum=0)
        new = self._used[name] + amount
        limit = getattr(self.budget, "max_" + name)
        if new > limit:
            raise PagedFactError("spool_" + name, stage="storage", limit=limit, observed=new)
        self._used[name] = new

    def charge_record(self):
        self.check()
        self._charge("records", 1)

    def usage(self):
        return dict(self._used)

    def _write_new(self, name, wire):
        self.check()
        if self._readonly:
            raise PagedFactError("store_readonly", stage="storage")
        self._charge("work_items", 1)
        self._charge("blocks", 1)
        self._charge("stored_bytes", len(wire))
        self._charge("io_bytes", len(wire))
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self._fd)
        try:
            offset = 0
            while offset < len(wire):
                count = os.write(fd, memoryview(wire)[offset:])
                if count <= 0:
                    raise OSError("short fact-store write")
                offset += count
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(self._fd)

    def bind_request(self, request):
        if self._request is not None or self._published is not None:
            raise PagedFactError("store_request_already_consumed", stage="admission")
        wire = _bounded_wire(request, self.profile.frame_bytes)
        if len(wire) > self.profile.frame_bytes:
            raise PagedFactError("request_frame", stage="admission")
        self._write_new("request.json", wire)
        self._request = cid_for_structured(request)
        return self._request

    def put(self, value):
        self.check()
        if self._request is None or self._published is not None:
            raise PagedFactError("store_not_writable", stage="storage")
        wire = _bounded_wire(value, self.profile.frame_bytes)
        cid = cid_for_structured(value)
        try:
            existing = self.get(cid)
        except FileNotFoundError:
            self._write_new(cid, wire)
        else:
            if existing != value:
                raise PagedFactError("fact_collision", stage="storage")
        return cid

    def get(self, cid):
        _cid(cid)
        return self._read_json(cid, cid)

    def _read_json(self, name, expected_cid=None):
        self.check()
        self._charge("work_items", 1)
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self._fd)
        try:
            before = os.fstat(fd)
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid() or before.st_nlink != 1 or
                    not 0 < before.st_size <= self.profile.frame_bytes):
                raise PagedFactError("fact_file_shape", stage="verification")
            self._charge("io_bytes", before.st_size)
            pieces, remaining = [], before.st_size + 1
            while remaining:
                piece = os.read(fd, min(65536, remaining))
                if not piece:
                    break
                pieces.append(piece)
                remaining -= len(piece)
            wire = b"".join(pieces)
            after = os.fstat(fd)
            named = os.stat(name, dir_fd=self._fd, follow_symlinks=False)
            if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
                    (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) or
                    not stat.S_ISREG(named.st_mode) or (named.st_dev, named.st_ino) != (after.st_dev, after.st_ino)):
                raise PagedFactError("fact_changed_during_read", stage="verification")
            value = json.loads(wire)
            if (len(wire) != before.st_size or _bounded_wire(value, self.profile.frame_bytes) != wire or
                    expected_cid is not None and cid_for_structured(value) != expected_cid):
                raise PagedFactError("fact_canonical_or_cid", stage="verification")
            return value
        except (json.JSONDecodeError, UnicodeError, TypeError, ValueError, RecursionError) as exc:
            if isinstance(exc, PagedFactError):
                raise
            raise PagedFactError("fact_canonical_or_cid", stage="verification") from exc
        finally:
            os.close(fd)

    def publish_raw_coverage(self, root_cid):
        """Publish only a descriptor already independently verified by the scanner."""
        _cid(root_cid)
        if self._request is None or self._published is not None:
            raise PagedFactError("publication_already_consumed", stage="publication")
        self.get(root_cid)
        marker = {"schema": "ipfs-datasets.raw-fact-publication@1", "request_cid": self._request,
                  "root_cid": root_cid, "semantic_reconstruction": False, "completion_authority": False}
        self._write_new("raw-coverage.json", canonical_dag_json_bytes(marker))
        self._published = root_cid

    def close(self):
        failure = None
        for name in ("_lease", "_fd"):
            fd = getattr(self, name, None)
            setattr(self, name, None)
            if fd is not None:
                try:
                    os.close(fd)
                except OSError as exc:
                    # Never retry a numeric descriptor after an uncertain close.
                    failure = failure or exc
        if failure is not None:
            raise failure

    def __enter__(self):
        self.check()
        return self

    def __exit__(self, *args):
        self.close()


def _page(level, items):
    return {"schema": INDEX_SCHEMA, "level": level, "items": items}


def _descriptor(cid, level, items):
    return {"cid": cid, "level": level, "count": len(items) if level == 0 else sum(i["count"] for i in items),
            "first": None if not items else items[0][0] if level == 0 else items[0]["first"],
            "last": None if not items else items[-1][0] if level == 0 else items[-1]["last"]}


def build_fact_index(store, pairs, *, _verify_only=False):
    """Bounded online tree over an already strictly ordered pair iterator."""
    levels = [[] for _ in range(store.profile.max_depth)]
    last = None
    emit = cid_for_structured if _verify_only else store.put
    def append(level, item):
        if level >= store.profile.max_depth:
            raise PagedFactError("index_depth", stage="index")
        items = levels[level]
        candidate = items + [item]
        if len(candidate) > store.profile.page_items or len(canonical_dag_json_bytes(_page(level, candidate))) > store.profile.frame_bytes:
            if not items:
                raise PagedFactError("index_item_frame", stage="index")
            sealed = list(items)
            items.clear()
            append(level + 1, _descriptor(emit(_page(level, sealed)), level, sealed))
        if len(canonical_dag_json_bytes(_page(level, items + [item]))) > store.profile.frame_bytes:
            raise PagedFactError("index_item_frame", stage="index")
        items.append(item)
    for pair in pairs:
        store._charge("work_items", 1)
        if type(pair) not in (tuple, list) or len(pair) != 2 or type(pair[0]) is not str or not pair[0]:
            raise PagedFactError("index_pair", stage="index")
        key, cid = pair
        _cid(cid)
        if last is not None and key <= last:
            raise PagedFactError("index_order", stage="index")
        if len(key.encode("utf-8")) > store.profile.frame_bytes:
            raise PagedFactError("index_key_frame", stage="index")
        append(0, [key, cid])
        last = key
    for level, items in enumerate(levels):
        if not items and (last is not None or level != 0):
            continue
        descriptor = _descriptor(emit(_page(level, items)), level, items)
        items.clear()
        if not any(levels[level + 1:]):
            return descriptor
        append(level + 1, descriptor)
    raise PagedFactError("index_depth", stage="index")


def iter_fact_index(store, descriptor):
    """Verify ranges/counts and each page CID before yielding bounded pairs.

    No set of all records is retained. Strictly disjoint ranges and decreasing
    depth reject cycles, duplicated subtrees and duplicate keys.
    """
    def walk(desc):
        _closed(desc, {"cid", "level", "count", "first", "last"})
        _cid(desc["cid"])
        _integer(desc["level"], "index_level", store.profile.max_depth - 1, 0)
        _integer(desc["count"], "index_count", store.budget.max_work_items, 0)
        page = _closed(store.get(desc["cid"]), {"schema", "level", "items"}, INDEX_SCHEMA)
        if type(page["level"]) is not int or page["level"] != desc["level"]:
            raise PagedFactError("index_level", stage="verification")
        items = page["items"]
        if type(items) is not list or len(items) > store.profile.page_items or (desc["level"] and not items):
            raise PagedFactError("index_items", stage="verification")
        count, first, last = 0, None, None
        for item in items:
            if desc["level"] == 0:
                if type(item) is not list or len(item) != 2 or type(item[0]) is not str or not item[0]:
                    raise PagedFactError("index_pair", stage="verification")
                _cid(item[1])
                iterator = (item,)
            else:
                _closed(item, {"cid", "level", "count", "first", "last"})
                if type(item["level"]) is not int or item["level"] != desc["level"] - 1 or not item["count"]:
                    raise PagedFactError("index_child_level", stage="verification")
                iterator = walk(item)
            for key, cid in iterator:
                store._charge("work_items", 1)
                if last is not None and key <= last:
                    raise PagedFactError("index_order", stage="verification")
                first, last, count = first if first is not None else key, key, count + 1
                yield key, cid
        if (count, first, last) != (desc["count"], desc["first"], desc["last"]):
            raise PagedFactError("index_range_or_count", stage="verification")
    yield from walk(descriptor)


def verify_fact_index(store, descriptor):
    expected = build_fact_index(store, iter_fact_index(store, descriptor), _verify_only=True)
    if expected != descriptor:
        raise PagedFactError("noncanonical_index_packing", stage="verification")
    return descriptor


__all__ = ["PagedFactProfile", "FactSpoolBudget", "PagedFactError", "OwnedFactStore",
           "admit_paging", "build_fact_index", "iter_fact_index", "verify_fact_index"]
