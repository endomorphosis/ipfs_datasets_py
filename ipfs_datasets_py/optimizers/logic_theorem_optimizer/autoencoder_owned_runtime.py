"""Bounded observations of one fresh owned runtime directory.

This is filesystem custody, never resource admission or an archive/cleanup
policy. The caller must precharge the exact runtime under the existing named
roots and guard its actual native owner before and after every observation.
Numbers and JSON receipts cannot supply that authority. No daemon is started,
file removed, charge changed or native lease released by this module.
"""
from __future__ import annotations

import copy
from collections import deque
import os
from pathlib import Path, PurePosixPath
import stat


SCHEMA = "owned-runtime-directory-observation/v1"
MAX_ENTRIES = 20_000
MAX_DEPTH = 128


class RuntimeDirectoryError(RuntimeError):
    pass


def _need(condition, message):
    if not condition:
        raise RuntimeDirectoryError(message)


def _path(value):
    raw = os.fspath(value)
    _need(type(raw) is str and raw.startswith("/") and not raw.startswith("//")
          and raw == os.path.normpath(raw) and "\0" not in raw,
          "normalized unaliased absolute directory path required")
    return Path(raw)


def _record(info):
    return dict(device=info.st_dev, inode=info.st_ino, uid=info.st_uid, gid=info.st_gid,
        mode=info.st_mode, nlink=info.st_nlink, bytes=info.st_size,
        mtime_ns=info.st_mtime_ns, ctime_ns=info.st_ctime_ns)


def _directory_identity(info):
    # Child creation legitimately changes directory nlink, size and timestamps.
    return {key: info[key] for key in ("device", "inode", "uid", "gid", "mode", "mount_id")}


class _LinuxBackend:
    simulation = False

    def open_directory(self, path):
        current = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            for name in path.parts[1:]:
                following = self.open_child_directory(current, name)
                os.close(current)
                current = following
            result, current = current, -1
            return result
        finally:
            if current >= 0:
                os.close(current)

    def open_child_directory(self, parent, name):
        return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                       dir_fd=parent)

    def identity(self, descriptor):
        info = _record(os.fstat(descriptor))
        with open(f"/proc/self/fdinfo/{descriptor}", "r", encoding="ascii") as stream:
            raw = stream.read(16385)
        _need(len(raw) <= 16384, "filesystem descriptor metadata byte bound exceeded")
        fields = [line.split(":", 1)[1].strip() for line in raw.splitlines()
                  if line.startswith("mnt_id:")]
        _need(len(fields) == 1 and fields[0].isdigit() and int(fields[0]) > 0,
              "exact Linux descriptor mount identity unavailable")
        return dict(info, mount_id=int(fields[0]))

    def entries(self, descriptor):
        names = []
        # Give readdir an independent open-file description, so retained FDs
        # and the second snapshot cannot inherit an exhausted directory offset.
        fresh = self.open_child_directory(descriptor, ".")
        try:
            with os.scandir(fresh) as entries:
                for entry in entries:
                    _need(len(names) < MAX_ENTRIES, "runtime directory entry bound exceeded")
                    names.append(entry.name)
        finally:
            self.close(fresh)
        return tuple(sorted(names))

    def entry(self, parent, name):
        # O_PATH|O_NOFOLLOW observes even a socket/FIFO/symlink without opening
        # its payload and provides mount identity for file bind mounts too.
        descriptor = os.open(name, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
        try:
            return self.identity(descriptor)
        finally:
            self.close(descriptor)

    def link(self, parent, name):
        return os.readlink(name, dir_fd=parent)

    def close(self, descriptor):
        os.close(descriptor)


def _internal_link(relative, target):
    _need(type(target) is str and target and len(target.encode()) <= 4096
          and not target.startswith("/") and "\0" not in target,
          "runtime symlink must have a bounded relative internal target")
    parts = list(PurePosixPath(relative).parent.parts)
    for part in target.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            _need(parts, "runtime symlink escapes its held root")
            parts.pop()
        else:
            parts.append(part)
    # Never resolve or follow a symlink, including a cycle or dangling target.
    return "/".join(parts) or "."


def _validate_alias_graph(rows):
    """Expand captured relative aliases without following filesystem paths.

    Lexical normalization alone is insufficient: d/back -> '..' followed by
    out -> 'd/back/../outside' escapes after expanding the first alias. Resolve
    components in kernel order, including '..' after prefix expansion. Missing
    traversed prefixes, cycles, non-directory prefixes and unknown type changes
    refuse observation. An absent terminal internal leaf remains diagnostic.
    """
    remaining_steps = MAX_ENTRIES * 64
    for name, row in rows.items():
        if row["kind"] != "symlink":
            continue
        cursor, pending, expansions = [], deque(name.split("/")), 0
        while pending:
            remaining_steps -= 1
            _need(remaining_steps >= 0, "runtime alias graph traversal bound exceeded")
            component = pending.popleft()
            if component in ("", "."):
                continue
            if component == "..":
                _need(cursor, "runtime expanded symlink escapes its held root")
                cursor.pop()
                continue
            cursor.append(component)
            candidate = "/".join(cursor)
            target = rows.get(candidate)
            if target is None:
                _need(not pending, "runtime alias has a missing traversed prefix")
                continue
            if target["kind"] == "symlink":
                expansions += 1
                _need(expansions <= 40, "runtime alias cycle or expansion limit exceeded")
                link = target["link"]
                _need(type(link) is str and link and not link.startswith("/"),
                      "runtime expanded alias is not relative")
                cursor.pop()
                pending.extendleft(reversed(link.split("/")))
            elif pending:
                _need(target["kind"] == "directory", "runtime alias traverses a non-directory prefix")
        row["resolved_target"] = "/".join(cursor) or "."


class OwnedRuntimeDirectory:
    """A retained directory/parent capability and bounded filesystem observer.

    Bind only a fresh empty same-UID 0700 directory after fixed durable
    precharge. Regular files, owned Unix sockets, lexically internal relative
    symlinks whose captured graph also resolves internally, and fully internal
    regular-file hardlinks are observed. No FIFO,
    device, foreign UID, submount or duplicate directory identity is admitted.
    Live changes within an observation fail closed rather than being ignored.
    Closing this object closes its FDs only; it does not release native/storage
    claims or delete the runtime. Same-UID hostile writers are not contained.
    """

    def __init__(self, path, *, expected_parent, expected_owner_uid, byte_limit,
                 entry_limit=MAX_ENTRIES, depth_limit=MAX_DEPTH, _backend=None):
        _need(_backend is None or getattr(_backend, "simulation", None) is True,
              "runtime test backend must explicitly identify simulation")
        _need(type(expected_owner_uid) is int and expected_owner_uid == os.geteuid(),
              "runtime must belong to the actual caller UID")
        _need(type(byte_limit) is int and 0 < byte_limit < 2**63
              and type(entry_limit) is int and 1 <= entry_limit <= MAX_ENTRIES
              and type(depth_limit) is int and 1 <= depth_limit <= MAX_DEPTH,
              "bounded positive byte, entry and depth constraints required")
        self._path, self._parent = _path(path), _path(expected_parent)
        _need(self._path.parent == self._parent and self._path != self._parent,
              "runtime must be a direct child of its exact expected parent")
        self._uid, self._bytes = expected_owner_uid, byte_limit
        self._entry_limit, self._depth_limit = entry_limit, depth_limit
        self._backend = _LinuxBackend() if _backend is None else _backend
        self._parent_fd = self._root_fd = None
        self._closed = False
        try:
            self._parent_fd = self._backend.open_directory(self._parent)
            parent = self._backend.identity(self._parent_fd)
            _need(stat.S_ISDIR(parent["mode"]) and parent["uid"] == self._uid
                  and not parent["mode"] & 0o022, "runtime parent must be owned and not writable by peers")
            self._parent_identity = _directory_identity(parent)
            self._root_fd = self._backend.open_child_directory(self._parent_fd, self._path.name)
            root = self._backend.identity(self._root_fd)
            _need(stat.S_ISDIR(root["mode"]) and root["uid"] == self._uid
                  and stat.S_IMODE(root["mode"]) == 0o700
                  and root["mount_id"] == parent["mount_id"], "fresh private runtime root required")
            self._root_identity = _directory_identity(root)
            _need(not self._backend.entries(self._root_fd), "runtime root must initially be empty")
            self._verify()
        except BaseException:
            self.close()
            raise

    def _verify(self):
        _need(not self._closed, "runtime directory binding is closed")
        for path, retained, expected in ((self._parent, self._parent_fd, self._parent_identity),
                                        (self._path, self._root_fd, self._root_identity)):
            _need(_directory_identity(self._backend.identity(retained)) == expected,
                  "held runtime directory identity changed")
            current = self._backend.open_directory(path)
            try:
                _need(_directory_identity(self._backend.identity(current)) == expected,
                      "runtime path identity changed")
            finally:
                self._backend.close(current)

    def _scan(self):
        rows, links, directories = {}, {}, set()
        total = 0

        def walk(descriptor, relative, depth):
            nonlocal total
            _need(depth <= self._depth_limit, "runtime directory depth bound exceeded")
            identity = self._backend.identity(descriptor)
            _need(identity["uid"] == self._uid, "foreign runtime directory UID")
            _need(identity["mount_id"] == self._root_identity["mount_id"], "runtime submount is unsupported")
            key = (identity["device"], identity["inode"])
            _need(key not in directories, "duplicate runtime directory identity")
            directories.add(key)
            _need(len(rows) < self._entry_limit, "runtime aggregate entry bound exceeded")
            rows[relative or "."] = dict(identity, kind="directory", charged_bytes=0)
            for name in self._backend.entries(descriptor):
                _need(name not in ("", ".", "..") and "/" not in name and "\0" not in name,
                      "invalid runtime directory entry name")
                rel = (relative + "/" if relative else "") + name
                info = self._backend.entry(descriptor, name)
                _need(info["uid"] == self._uid, "foreign runtime entry UID")
                _need(info["mount_id"] == self._root_identity["mount_id"], "runtime submount is unsupported")
                if stat.S_ISDIR(info["mode"]):
                    child = self._backend.open_child_directory(descriptor, name)
                    try:
                        opened = self._backend.identity(child)
                        _need(all(opened[field] == info[field] for field in info),
                              "runtime directory changed while opened")
                        walk(child, rel, depth + 1)
                    finally:
                        self._backend.close(child)
                else:
                    _need(len(rows) < self._entry_limit, "runtime aggregate entry bound exceeded")
                    row = dict(info, charged_bytes=info["bytes"])
                    if stat.S_ISREG(info["mode"]):
                        row["kind"] = "file"
                        links.setdefault((info["device"], info["inode"]), []).append(info["nlink"])
                    elif stat.S_ISLNK(info["mode"]):
                        _need(info["nlink"] == 1, "hardlinked runtime symlink is unsupported")
                        target = self._backend.link(descriptor, name)
                        row.update(kind="symlink", link=target, lexical_target=_internal_link(rel, target))
                    else:
                        _need(stat.S_ISSOCK(info["mode"]) and info["nlink"] == 1,
                              "runtime FIFO, device or other special entry is unsupported")
                        row["kind"] = "unix_socket"
                    _need(self._backend.entry(descriptor, name) == info,
                          "runtime entry changed while observed")
                    total += row["charged_bytes"]
                    _need(total <= self._bytes, "runtime byte limit exceeded")
                    rows[rel] = row
            _need(self._backend.identity(descriptor) == identity,
                  "runtime directory changed during observation")

        walk(self._root_fd, "", 0)
        for copies in links.values():
            _need(all(count == len(copies) for count in copies),
                  "runtime hardlink has outside copies or changed during observation")
        _validate_alias_graph(rows)
        return rows, total

    def observe(self):
        """Compare two complete bounded non-following snapshots, without writes."""
        try:
            self._verify()
            rows, total = self._scan()
            self._verify()
            confirmed, confirmed_bytes = self._scan()
            _need(rows == confirmed and total == confirmed_bytes,
                  "runtime changed between bounded observations")
            self._verify()
            return dict(schema=SCHEMA, path=str(self._path), expected_parent=str(self._parent),
                root_identity=copy.deepcopy(self._root_identity),
                parent_identity=copy.deepcopy(self._parent_identity),
                simulation=self._backend.simulation, entries=rows, entry_count=len(rows),
                apparent_bytes=total, byte_limit=self._bytes, entry_limit=self._entry_limit,
                stable_double_snapshot=True, observation_atomic=False,
                accounting_scope="lstat_bytes_per_path_in_original_held_runtime",
                native_ownership_authenticated=False, external_charge_authenticated=False,
                resource_admission=False, ledger_changed=False, files_deleted=False,
                observation_only=True, hostile_same_uid_confinement=False,
                ordinary_strict_filesystem_profile_passed=False, admitted=False, Lean_admitted=False)
        except OSError as error:
            raise RuntimeDirectoryError("owned runtime observation unavailable") from error

    def close(self):
        if not self._closed:
            self._closed = True
            for descriptor in (self._root_fd, self._parent_fd):
                if descriptor is not None:
                    self._backend.close(descriptor)
            self._root_fd = self._parent_fd = None


__all__ = ["OwnedRuntimeDirectory", "RuntimeDirectoryError", "SCHEMA"]
