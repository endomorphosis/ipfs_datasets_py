"""Opt-in pytest tmp_path profile for strict owned regular-file inventories.

Use ``-p ipfs_datasets_py.optimizers.logic_theorem_optimizer.validation_pytest``.
Unlike pytest's numbered tmp_path helper, this fixture creates no convenience
``...current`` symlink. Every test still receives a unique private directory;
all directories are retained as validation evidence. The factory fixture itself
is unchanged unless ``--owned-ordinary-temp-factory`` is explicitly selected.
That session profile retains unique private factory directories without numbered
convenience symlinks; unnumbered calls still use the original factory. No test
assertions or selection rules change.

The explicit ``--owned-physical-fixtures`` v2 profile maps only the frozen
selected cases to owner-created directories outside that basetemp. It verifies
their final ordinary trees without deleting or repairing test-created entries.
"""
from __future__ import annotations

from pathlib import Path
import hashlib
import json
import os
import re
import stat
import tempfile

import pytest


_REQUEST_ENV = "IPFS_DATASETS_OWNED_VALIDATION_REQUEST"
_REQUEST_SHA_ENV = "IPFS_DATASETS_OWNED_VALIDATION_REQUEST_SHA256"
_REQUEST_FIELDS = {"schema", "argv", "cwd", "selected_checks", "source_sha256",
    "timeout_seconds", "storage_bytes", "memory_mb", "cpu_slots",
    "child_process_slots", "attempt_directory", "outputs",
    "declared_external_writable_paths", "process_scope", "scheduler_state_path",
    "expected_scheduler_policy_sha256", "roots", "physical_fixture_profile"}
_MAX_PHYSICAL_CASES = 32
_MAX_PHYSICAL_ENTRIES = 128
_MAX_PHYSICAL_DEPTH = 16
_MAX_PHYSICAL_INVENTORY_ENTRIES = 20_000


def _need(condition, message):
    if not condition:
        raise pytest.UsageError("owned physical fixtures: " + message)


def _identity(info):
    return info.st_dev, info.st_ino, info.st_uid, info.st_mode


def _directory(path, *, private=False):
    path = Path(path)
    _need(path.is_absolute() and ".." not in path.parts, "absolute directory required")
    for parent in (*reversed(path.parents), path):
        _need(stat.S_ISDIR(parent.lstat().st_mode), "unaliased directory ancestry required")
    info = path.lstat()
    _need(info.st_uid == os.geteuid(), "directory must belong to the current user")
    _need(stat.S_IMODE(info.st_mode) == 0o700 if private else not info.st_mode & 0o022,
          "private directory permissions differ")
    return _identity(info)


def _request_bytes(path):
    path = Path(path)
    _need(path.is_absolute() and ".." not in path.parts, "absolute request path required")
    for parent in path.parents:
        _need(stat.S_ISDIR(parent.lstat().st_mode), "unaliased request ancestry required")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        before = os.fstat(descriptor)
        _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
              and before.st_uid == os.geteuid() and 0 < before.st_size <= 1_048_576,
              "bounded ordinary request required")
        pieces, remaining = [], before.st_size
        while remaining:
            piece = os.read(descriptor, min(remaining, 65_536))
            _need(bool(piece), "request was truncated")
            pieces.append(piece)
            remaining -= len(piece)
        _need(os.read(descriptor, 1) == b"", "request grew")
        after, current = os.fstat(descriptor), path.lstat()
        stable = lambda info: (_identity(info), info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        _need(stable(before) == stable(after) == stable(current), "request changed")
        return b"".join(pieces)
    finally:
        os.close(descriptor)


def _pairs(items):
    result = {}
    for key, value in items:
        _need(key not in result, "duplicate JSON field")
        result[key] = value
    return result


def _relative(value):
    _need(type(value) is str and 0 < len(value) <= 256 and "\\" not in value
          and "\x00" not in value, "invalid relative fixture path")
    parts = value.split("/")
    _need(len(parts) <= 8 and all(part not in ("", ".", "..") for part in parts),
          "fixture path must have plain relative components")
    _need(not Path(value).is_absolute(), "absolute fixture path forbidden")
    value.encode("utf-8")
    return value


def _absolute_nodeid(item):
    path, separator, suffix = item.nodeid.partition("::")
    _need(bool(separator) and bool(suffix), "concrete pytest node ID required")
    actual = Path(item.path)
    _need(actual.is_absolute(), "absolute collected test path required")
    return str(actual) + "::" + suffix


def _load_profile(config):
    enabled = config.getoption("owned_physical_fixtures")
    spelling, digest = os.environ.get(_REQUEST_ENV), os.environ.get(_REQUEST_SHA_ENV)
    if not enabled and spelling is None and digest is None:
        return None
    _need(enabled is True and type(spelling) is str and bool(spelling)
          and type(digest) is str and re.fullmatch("[0-9a-f]{64}", digest),
          "flag and paired owner request environment are required together")
    raw = _request_bytes(spelling)
    _need(hashlib.sha256(raw).hexdigest() == digest, "frozen request hash differs")
    value = json.loads(raw, object_pairs_hook=_pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    _need(type(value) is dict and set(value) == _REQUEST_FIELDS
          and value["schema"] == "owned-validation-request/v2", "closed v2 request required")
    selected = value["selected_checks"]
    _need(type(selected) is list and 0 < len(selected) <= 256
          and all(type(node) is str and 0 < len(node) <= 8192 and "\x00" not in node
                  for node in selected) and len(set(selected)) == len(selected),
          "exact unique frozen selected checks required")
    for node in selected:
        path, separator, suffix = node.partition("::")
        _need(bool(separator) and bool(suffix) and Path(path).is_absolute()
              and ".." not in Path(path).parts, "absolute frozen node IDs required")
        node.encode("utf-8")
    _need(type(value["storage_bytes"]) is int and value["storage_bytes"] > 0,
          "positive original storage promise required")
    attempt = value["attempt_directory"]
    _need(type(attempt) is str and Path(attempt).is_absolute()
          and ".." not in Path(attempt).parts, "absolute owned attempt required")
    profile = value["physical_fixture_profile"]
    _need(type(profile) is dict and set(profile) == {"schema", "root", "cases"}
          and profile["schema"] == "owned-validation-physical-fixtures/v1"
          and profile["root"] == str(Path(attempt) / "tmp" / "physical-fixtures"),
          "exact physical fixture profile and owned root required")
    root = Path(profile["root"])
    root_identity = _directory(root, private=True)
    rows = profile["cases"]
    _need(type(rows) is list and 1 <= len(rows) <= _MAX_PHYSICAL_CASES,
          "bounded nonempty physical fixture cases required")
    cases, total = {}, 0
    for row in rows:
        _need(type(row) is dict and set(row) == {"nodeid", "entries"}, "closed case required")
        node = row["nodeid"]
        _need(type(node) is str and node in selected and node not in cases,
              "unique case must match an exact frozen selected check")
        entries = row["entries"]
        _need(type(entries) is list and 1 <= len(entries) <= 4, "bounded typed entries required")
        seen = set()
        for entry in entries:
            _need(type(entry) is dict and set(entry) == {"path", "kind", "target", "target_kind"},
                  "closed typed fixture entry required")
            relative = _relative(entry["path"])
            _need(relative not in seen, "duplicate fixture entry path")
            seen.add(relative)
            if entry["kind"] == "fifo":
                _need(entry["target"] is None and entry["target_kind"] is None,
                      "FIFO cannot have a symlink target")
            else:
                _need(entry["kind"] == "symlink" and entry["target_kind"] in ("file", "directory")
                      and type(entry["target_kind"]) is str, "unsupported fixture kind or target type")
                target = _relative(entry["target"])
                _need(target != relative, "fixture cannot target itself")
        _need(not any(left != right and right.startswith(left + "/")
                      for left in seen for right in seen),
              "declared special paths cannot be ancestors of one another")
        for entry in entries:
            if entry["kind"] == "symlink":
                _need(not any(entry["target"] == special
                              or entry["target"].startswith(special + "/") for special in seen),
                      "symlink target cannot equal or descend from a special slot")
        total += len(entries)
        _need(total <= _MAX_PHYSICAL_ENTRIES, "too many declared fixture entries")
        path = root / hashlib.sha256(node.encode("utf-8")).hexdigest()
        for entry in entries:
            if entry["kind"] == "symlink":
                _need(len(str(path / entry["target"]).encode("utf-8")) <= 4096,
                      "expected symlink literal is too long")
        cases[node] = {"path": path, "identity": _directory(path, private=True)}
    return {"request": Path(spelling), "raw": raw, "root": root,
            "root_identity": root_identity, "cases": cases,
            "selected": selected, "storage_bytes": value["storage_bytes"],
            "started": set(), "closed": set()}


def _guard_profile(profile, node):
    _need(_request_bytes(profile["request"]) == profile["raw"], "frozen request changed")
    _need(_directory(profile["root"], private=True) == profile["root_identity"],
          "fixture root identity changed")
    case = profile["cases"][node]
    _need(_directory(case["path"], private=True) == case["identity"],
          "fixture case directory identity changed")
    return case["path"]


def _strict_final_tree(descriptor, budget):
    """Verify an anchored ordinary tree; never open an alias, FIFO or file body."""
    count, total = 0, 0

    def visit(directory, depth):
        nonlocal count, total
        _need(depth <= _MAX_PHYSICAL_DEPTH, "final fixture tree is too deep")
        directory_before = os.fstat(directory)
        with os.scandir(directory) as entries:
            for entry in entries:
                _need(depth + 1 <= _MAX_PHYSICAL_DEPTH, "final fixture tree is too deep")
                count += 1
                _need(count <= _MAX_PHYSICAL_INVENTORY_ENTRIES, "too many final fixture entries")
                before = entry.stat(follow_symlinks=False)
                _need(before.st_uid == os.geteuid(), "final fixture entry owner differs")
                if stat.S_ISDIR(before.st_mode):
                    _need(not before.st_mode & 0o022, "writable shared final fixture directory")
                    child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                                    | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory)
                    try:
                        _need(_identity(os.fstat(child)) == _identity(before),
                              "final fixture directory changed during open")
                        visit(child, depth + 1)
                    finally:
                        os.close(child)
                else:
                    _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
                          "final fixture alias or special file remains")
                    total += before.st_size
                    _need(total <= budget, "final fixture bytes exceed original storage promise")
                after = os.stat(entry.name, dir_fd=directory, follow_symlinks=False)
                _need(_identity(before) == _identity(after)
                      and before.st_nlink == after.st_nlink and before.st_size == after.st_size
                      and before.st_mtime_ns == after.st_mtime_ns
                      and before.st_ctime_ns == after.st_ctime_ns,
                      "final fixture entry changed during inspection")
        directory_after = os.fstat(directory)
        _need(_identity(directory_before) == _identity(directory_after)
              and directory_before.st_mtime_ns == directory_after.st_mtime_ns
              and directory_before.st_ctime_ns == directory_after.st_ctime_ns,
              "final fixture directory changed during inspection")
    visit(descriptor, 0)


def pytest_addoption(parser):
    parser.getgroup("owned validation").addoption("--owned-physical-fixtures", action="store_true",
        default=False, help="Use the exact owner-pinned v2 physical fixture request")
    parser.getgroup("owned validation").addoption("--owned-ordinary-temp-factory", action="store_true",
        default=False, help="Retain ordinary private session factory directories without numbered aliases")


def pytest_configure(config):
    try:
        config._owned_physical_fixture_profile = _load_profile(config)
    except (OSError, ValueError, TypeError, KeyError, UnicodeError) as error:
        raise pytest.UsageError("owned physical fixtures: invalid frozen request: " + str(error)) from error


def pytest_collection_modifyitems(session, config, items):
    profile = getattr(config, "_owned_physical_fixture_profile", None)
    if profile is not None:
        collected = [_absolute_nodeid(item) for item in items]
        _need(collected == profile["selected"], "actual selected node IDs differ from frozen request")


def pytest_sessionfinish(session, exitstatus):
    profile = getattr(session.config, "_owned_physical_fixture_profile", None)
    if profile is not None and exitstatus == 0 and profile["closed"] != set(profile["cases"]):
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


class _OrdinaryTempPathFactory:
    """Explicit fixture adapter; the original pytest factory is never modified."""

    def __init__(self, factory, configured):
        if configured is None or not Path(configured).is_absolute() or ".." in Path(configured).parts:
            raise pytest.UsageError("owned ordinary temp factory requires explicit absolute --basetemp")
        self._factory = factory
        self._configured = Path(configured)

    def getbasetemp(self):
        return self._factory.getbasetemp()

    def mktemp(self, basename, numbered=True):
        if not numbered:
            return self._factory.mktemp(basename, numbered=numbered)
        base = Path(self.getbasetemp())
        if base != self._configured:
            raise pytest.UsageError("owned ordinary temp factory requires the exact absolute basetemp")
        for parent in (base, *base.parents):
            if not stat.S_ISDIR(parent.lstat().st_mode):
                raise pytest.UsageError("owned ordinary temp factory requires unaliased directory ancestry")
        info = base.lstat()
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise pytest.UsageError("owned ordinary temp factory requires a private owned basetemp")
        basename = self._factory._ensure_relative_to_basetemp(basename)
        return Path(tempfile.mkdtemp(prefix=basename + "-", dir=base))


@pytest.fixture(scope="session")
def tmp_path_factory(request, tmp_path_factory):
    """Keep pytest's factory by default; adapt numbered calls only on opt-in."""
    if not request.config.getoption("owned_ordinary_temp_factory"):
        return tmp_path_factory
    return _OrdinaryTempPathFactory(tmp_path_factory, request.config.option.basetemp)


@pytest.fixture
def tmp_path(request, tmp_path_factory):
    """A function-scoped private directory below the explicit owned basetemp."""
    profile = getattr(request.config, "_owned_physical_fixture_profile", None)
    node = _absolute_nodeid(request.node) if profile is not None else None
    if profile is not None and node in profile["cases"]:
        _need(node not in profile["started"], "mapped fixture cannot be reused")
        path = _guard_profile(profile, node)
        _need(not any(path.iterdir()), "mapped fixture must initially be empty")
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            _need(_identity(os.fstat(descriptor)) == profile["cases"][node]["identity"],
                  "mapped case changed during open")
        except BaseException:
            os.close(descriptor)
            raise
        profile["started"].add(node)

        def verify_finalized():
            try:
                _guard_profile(profile, node)
                _need(_identity(os.fstat(descriptor)) == profile["cases"][node]["identity"],
                      "held case directory changed")
                _strict_final_tree(descriptor, profile["storage_bytes"])
                _guard_profile(profile, node)
                profile["closed"].add(node)
            finally:
                os.close(descriptor)
        request.addfinalizer(verify_finalized)
        return path
    configured = request.config.option.basetemp
    if configured is None:
        raise pytest.UsageError('owned validation requires explicit --basetemp')
    base = Path(tmp_path_factory.getbasetemp())
    if not Path(configured).is_absolute() or base != Path(configured):
        raise pytest.UsageError('owned validation requires the exact absolute basetemp')
    for parent in (base, *base.parents):
        if not stat.S_ISDIR(parent.lstat().st_mode):
            raise pytest.UsageError('owned validation basetemp must be an unaliased directory')
    name = re.sub(r'[^A-Za-z0-9_]', '_', request.node.name)[:48]
    return Path(tempfile.mkdtemp(prefix=name+'-', dir=base))
