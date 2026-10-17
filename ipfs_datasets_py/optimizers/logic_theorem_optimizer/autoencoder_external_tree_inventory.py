"""Bounded, metadata-only inventories of an exact external directory tree.

Only directories are opened. Regular-file payloads (including databases,
credentials and models) are never opened or hashed. Symlink resolution uses
directory descriptors and metadata; links are never enqueued for enumeration.
The returned observations are non-atomic snapshots, not continuous custody.
Repeated checks cannot exclude namespace ABA changes between observations.
"""
from __future__ import annotations

from collections import deque
import hashlib
import json
import os
from pathlib import Path
import stat


SCHEMA = "autoencoder-external-tree-descriptor-inventory@1"
OPAQUE_SCHEMA = "autoencoder-external-tree-descriptor-inventory@2"
MAX_OPAQUE_SYMLINKS = 128
MAX_ENTRIES = 65_536
MAX_COUNT = (1 << 63) - 1
MAX_DEPTH = 256
MAX_SYMLINK_HOPS = 256
MAX_PATH_BYTES = 4_096
MAX_LINK_TARGET_BYTES = 4_096
MAX_SERIALIZED_BYTES = 64 * 1024 * 1024
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _need(condition, reason):
    if not condition:
        raise ValueError(reason)


def _identity(info):
    return {
        "device": info.st_dev,
        "inode": info.st_ino,
        "mode": info.st_mode,
        "uid": info.st_uid,
        "gid": info.st_gid,
        "nlink": info.st_nlink,
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "ctime_ns": info.st_ctime_ns,
    }


def _namespace_identity(info):
    # Sibling creation in ancestors outside the selected root is unrelated to
    # the observed tree. Retain their namespace identity, not sibling times.
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink)


def _kind(info):
    if stat.S_ISDIR(info.st_mode):
        return "directory"
    if stat.S_ISREG(info.st_mode):
        return "regular"
    if stat.S_ISLNK(info.st_mode):
        return "symlink"
    raise ValueError("external_tree_special_inode_refused")


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def _opaque_manifest(value, bounds):
    if value is None:
        return None
    _need(type(value) is list and 1 <= len(value)
          <= min(MAX_OPAQUE_SYMLINKS, bounds["max_entries"]),
          "external_tree_opaque_manifest_bound_or_type")
    result, previous = [], None
    for row in value:
        _need(type(row) is dict and set(row) == {"path", "link_target"},
              "external_tree_opaque_manifest_fields")
        path, target = row["path"], row["link_target"]
        _need(type(path) is str and path and len(path) <= MAX_PATH_BYTES
              and path != "." and "\x00" not in path,
              "external_tree_opaque_path_invalid")
        relative = Path(path)
        _need(not relative.is_absolute() and str(relative) == path
              and ".." not in relative.parts
              and len(relative.parts) <= bounds["max_depth"]
              and len(os.fsencode(path)) <= MAX_PATH_BYTES
              and (previous is None or previous < path),
              "external_tree_opaque_path_not_canonical_or_unique")
        _need(type(target) is str and target and len(target) <= MAX_LINK_TARGET_BYTES
              and "\x00" not in target
              and len(os.fsencode(target)) <= MAX_LINK_TARGET_BYTES,
              "external_tree_opaque_literal_target_invalid")
        previous = path
        result.append({"path": path, "link_target": target})
    return result


def _open_directory(parent_fd, name, expected):
    """Bind a named directory to its observed complete metadata generation."""
    _need(stat.S_ISDIR(expected.st_mode), "external_tree_directory_required")
    fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
    try:
        _need(_identity(os.fstat(fd)) == _identity(expected)
              == _identity(os.stat(name, dir_fd=parent_fd, follow_symlinks=False)),
              "external_tree_directory_changed_on_open")
        return fd
    except BaseException:
        os.close(fd)
        raise


class _Observation:
    def __init__(self, root, bounds, opaque_symlinks=None):
        self.root = root
        self.root_parts = root.parts[1:]
        self.bounds = bounds
        self.anchors = []
        self.root_fd = None
        self.root_info = None
        self.witnesses = {}
        self.rows = []
        self.apparent_bytes = 0
        self.encoded_entry_bytes = 0
        self.resolution_steps = 0
        self.opaque_manifest = opaque_symlinks
        self.opaque = {tuple(row["path"].split("/")): row["link_target"]
                       for row in opaque_symlinks or ()}
        self.opaque_seen = set()

    def _relative(self, parts):
        _need(len(parts) <= self.bounds["max_depth"],
              "external_tree_depth_bound")
        value = "/".join(parts) if parts else "."
        _need(len(os.fsencode(value)) <= MAX_PATH_BYTES,
              "external_tree_relative_path_bound")
        return value

    def _pending_bound(self, parts):
        _need(sum(len(os.fsencode(part)) + 1 for part in parts) <= MAX_PATH_BYTES,
              "external_tree_resolution_path_bound")

    def _step(self):
        self.resolution_steps += 1
        _need(self.resolution_steps <= self.bounds["max_resolution_steps"],
              "external_tree_resolution_step_bound")

    def _remember(self, parts, info):
        self._relative(parts)
        _kind(info)
        value = _identity(info)
        old = self.witnesses.get(parts)
        _need(old is None or old == value, "external_tree_entry_generation_changed")
        self.witnesses[parts] = value
        _need(len(self.witnesses) <= self.bounds["max_entries"] + 1,
              "external_tree_witness_entry_bound")

    def _readlink(self, parent_fd, name, info):
        target = os.readlink(name, dir_fd=parent_fd)
        _need(type(target) is str and target and "\x00" not in target,
              "external_tree_link_target_invalid")
        length = len(os.fsencode(target))
        _need(length <= MAX_LINK_TARGET_BYTES and length == info.st_size,
              "external_tree_link_target_bound_or_generation")
        _need(_identity(os.stat(name, dir_fd=parent_fd, follow_symlinks=False))
              == _identity(info), "external_tree_link_changed_during_read")
        return target

    def _redirect(self, prefix, target):
        # Do not normalize '..' before expanding each preceding symlink.
        parts = target.split("/")
        if target.startswith("/"):
            parts = [part for part in parts if part != ""]
            _need(tuple(parts[:len(self.root_parts)]) == self.root_parts,
                  "external_tree_absolute_link_escape")
            return parts[len(self.root_parts):]
        return list(prefix) + parts

    def _resolve(self, parts):
        """Resolve metadata only; every parent step stays under the held root."""
        self._pending_bound(parts)
        pending = deque(parts)
        prefix = []
        hops = 1
        _need(hops <= self.bounds["max_symlink_hops"],
              "external_tree_symlink_hop_bound")
        seen_links = set()
        fd = os.dup(self.root_fd)
        try:
            while pending:
                self._step()
                component = pending.popleft()
                if component in ("", "."):
                    continue
                if component == "..":
                    _need(prefix, "external_tree_parent_link_escape")
                    pending = deque(prefix[:-1] + list(pending))
                    prefix = []
                    fresh_fd = os.dup(self.root_fd)
                    os.close(fd)
                    fd = fresh_fd
                    continue
                _need("/" not in component and "\x00" not in component,
                      "external_tree_component_invalid")
                relative = tuple(prefix + [component])
                info = os.stat(component, dir_fd=fd, follow_symlinks=False)
                self._remember(relative, info)
                kind = _kind(info)
                # A listed leaf is not an internal routing alias, including
                # when its current inode was replaced by another type.
                if relative in self.opaque:
                    _need(kind == "symlink", "external_tree_opaque_manifest_requires_symlink")
                    _need(self._readlink(fd, component, info) == self.opaque[relative],
                          "external_tree_opaque_literal_target_changed")
                    raise ValueError("external_tree_opaque_link_in_resolved_chain")
                if kind == "symlink":
                    hops += 1
                    _need(hops <= self.bounds["max_symlink_hops"],
                          "external_tree_symlink_hop_bound")
                    state = (relative, info.st_dev, info.st_ino, tuple(pending))
                    _need(state not in seen_links, "external_tree_symlink_cycle")
                    seen_links.add(state)
                    target = self._readlink(fd, component, info)
                    redirected = self._redirect(prefix, target) + list(pending)
                    self._pending_bound(redirected)
                    pending = deque(redirected)
                    prefix = []
                    fresh_fd = os.dup(self.root_fd)
                    os.close(fd)
                    fd = fresh_fd
                elif kind == "directory":
                    child_fd = _open_directory(fd, component, info)
                    os.close(fd)
                    fd = child_fd
                    prefix.append(component)
                else:
                    _need(not pending, "external_tree_non_directory_link_component")
                    _need(_identity(os.stat(component, dir_fd=fd, follow_symlinks=False))
                          == _identity(info), "external_tree_link_target_changed")
                    prefix.append(component)
            return self._relative(tuple(prefix))
        finally:
            os.close(fd)

    def _walk(self, fd, relative):
        before = os.fstat(fd)
        self._remember(relative, before)
        with os.scandir(fd) as listing:
            for entry in listing:
                _need(len(self.rows) < self.bounds["max_entries"],
                      "external_tree_entry_bound")
                name = entry.name
                _need(type(name) is str and name not in ("", ".", "..")
                      and "/" not in name and "\x00" not in name,
                      "external_tree_entry_name_invalid")
                parts = relative + (name,)
                path = self._relative(parts)
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                self._remember(parts, info)
                kind = _kind(info)
                _need(parts not in self.opaque or kind == "symlink",
                      "external_tree_opaque_manifest_requires_symlink")
                row = {"path": path, "kind": kind, **_identity(info),
                       "link_target": None, "resolved_target": None}
                if kind == "symlink":
                    raw = self._readlink(fd, name, info)
                    row["link_target"] = raw
                    if parts in self.opaque:
                        _need(raw == self.opaque[parts] and parts not in self.opaque_seen,
                              "external_tree_opaque_literal_target_or_occurrence")
                        self.opaque_seen.add(parts)
                    else:
                        row["resolved_target"] = self._resolve(self._redirect(relative, raw))
                if kind != "directory":
                    self.apparent_bytes += info.st_size
                    _need(self.apparent_bytes <= self.bounds["max_bytes"],
                          "external_tree_byte_bound")
                self.encoded_entry_bytes += len(_canonical(row)) + 1
                _need(self.encoded_entry_bytes <= MAX_SERIALIZED_BYTES - 131_072,
                      "external_tree_serialized_entry_bound")
                self.rows.append(row)
                if kind == "directory":
                    child_fd = _open_directory(fd, name, info)
                    try:
                        self._walk(child_fd, parts)
                        _need(_identity(os.fstat(child_fd)) == _identity(info),
                              "external_tree_directory_changed_during_walk")
                    finally:
                        os.close(child_fd)
                _need(_identity(os.stat(name, dir_fd=fd, follow_symlinks=False))
                      == _identity(info), "external_tree_entry_changed_during_walk")
        _need(_identity(os.fstat(fd)) == _identity(before),
              "external_tree_held_directory_changed_during_walk")

    def _recheck_witness(self, parts, expected):
        fd = os.dup(self.root_fd)
        try:
            if not parts:
                _need(_identity(os.fstat(fd)) == expected,
                      "external_tree_root_generation_changed")
                return
            prefix = ()
            for component in parts[:-1]:
                self._step()
                info = os.stat(component, dir_fd=fd, follow_symlinks=False)
                prefix += (component,)
                _need(_identity(info) == self.witnesses[prefix],
                      "external_tree_witness_parent_changed")
                child_fd = _open_directory(fd, component, info)
                os.close(fd)
                fd = child_fd
            self._step()
            _need(_identity(os.stat(parts[-1], dir_fd=fd, follow_symlinks=False))
                  == expected, "external_tree_final_entry_changed")
        finally:
            os.close(fd)

    def _recheck_opaque_literal(self, parts):
        """Re-read only the listed link's literal through no-follow parents."""
        fd = os.dup(self.root_fd)
        try:
            prefix = ()
            for component in parts[:-1]:
                self._step()
                info = os.stat(component, dir_fd=fd, follow_symlinks=False)
                prefix += (component,)
                _need(_identity(info) == self.witnesses[prefix],
                      "external_tree_opaque_parent_changed")
                child_fd = _open_directory(fd, component, info)
                os.close(fd)
                fd = child_fd
            self._step()
            info = os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
            _need(_identity(info) == self.witnesses[parts],
                  "external_tree_opaque_link_generation_changed")
            _need(self._readlink(fd, parts[-1], info) == self.opaque[parts],
                  "external_tree_opaque_literal_target_changed")
        finally:
            os.close(fd)

    def _anchor(self):
        fd = os.open("/", _DIRECTORY_FLAGS)
        try:
            before = os.fstat(fd)
        except BaseException:
            os.close(fd)
            raise
        self.anchors.append(("/", fd, before))
        for component in self.root_parts:
            parent = self.anchors[-1][1]
            info = os.stat(component, dir_fd=parent, follow_symlinks=False)
            fd = _open_directory(parent, component, info)
            self.anchors.append((component, fd, info))
        self.root_fd = self.anchors[-1][1]
        self.root_info = os.fstat(self.root_fd)
        self._remember((), self.root_info)

    def _recheck_anchors(self):
        for index, (name, fd, before) in enumerate(self.anchors):
            current = (os.stat("/", follow_symlinks=False) if index == 0 else
                       os.stat(name, dir_fd=self.anchors[index - 1][1],
                               follow_symlinks=False))
            _need(_namespace_identity(current) == _namespace_identity(before)
                  == _namespace_identity(os.fstat(fd)),
                  "external_tree_named_anchor_changed")
        _need(_identity(os.fstat(self.root_fd)) == _identity(self.root_info),
              "external_tree_root_generation_changed")

    def run(self):
        try:
            self._anchor()
            self._walk(self.root_fd, ())
            _need(self.opaque_seen == set(self.opaque),
                  "external_tree_opaque_manifest_not_fully_observed")
            # Recheck all metadata witnesses, including intermediate link
            # targets, through freshly opened no-follow directory descriptors.
            for parts, expected in tuple(self.witnesses.items()):
                self._recheck_witness(parts, expected)
            for row in self.rows:
                if row["kind"] == "symlink":
                    parts = tuple(row["path"].split("/"))
                    if parts in self.opaque:
                        self._recheck_opaque_literal(parts)
                    else:
                        _need(self._resolve(self._redirect(parts[:-1], row["link_target"]))
                              == row["resolved_target"], "external_tree_link_resolution_changed")
            self._recheck_anchors()
            result = {
                "schema": SCHEMA if self.opaque_manifest is None else OPAQUE_SCHEMA,
                "root_path": str(self.root),
                "root_identity": _identity(self.root_info),
                "entries": sorted(self.rows, key=lambda row: row["path"]),
                "entry_count": len(self.rows),
                "apparent_bytes": self.apparent_bytes,
                "bounds": dict(self.bounds),
                "metadata_only": True,
                "payload_files_opened": False,
                "symlink_directories_enqueued": False,
                "directory_open_no_follow": True,
                "atomic_snapshot": False,
                "continuous_custody_proved": False,
            }
            if self.opaque_manifest is not None:
                result.update(
                    symlink_resolution="internal_except_explicit_opaque",
                    opaque_symlinks=self.opaque_manifest,
                    opaque_link_referents_observed=False,
                    opaque_link_target_custody_asserted=False,
                    opaque_link_target_durability_asserted=False,
                )
            encoded = _canonical(result)
            _need(len(encoded) <= MAX_SERIALIZED_BYTES - 100,
                  "external_tree_serialized_inventory_bound")
            result["inventory_sha256"] = hashlib.sha256(encoded).hexdigest()
            # Round-trip only our bounded constructed metadata, returning no
            # caller-owned mutable objects or stat-result implementation types.
            return json.loads(_canonical(result))
        finally:
            for _, fd, _ in reversed(self.anchors):
                os.close(fd)
            self.anchors.clear()


def observe_external_tree(path, *, max_entries, max_bytes, max_depth=64,
                          max_symlink_hops=40, opaque_symlinks=None):
    """Return a closed descriptor census without opening any file payload.

    Root depth is zero; every relative entry/target component counts toward
    max_depth. Hard links count once per pathname with explicit nlink metadata.
    Policy refusals raise ValueError; failed filesystem operations raise OSError.
    Callers must separately establish custody and compare fresh observations.
    The default is unchanged schema @1. An explicit, sorted, nonempty manifest
    opts into schema @2: listed link literals are observed, their referents are
    never inspected, and their resolved_target stays None. All unlisted links
    retain strict contained resolution; a chain reaching an opaque leaf refuses.
    """
    for value, maximum, name in (
        (max_entries, MAX_ENTRIES, "entries"),
        (max_bytes, MAX_COUNT, "bytes"),
        (max_depth, MAX_DEPTH, "depth"),
        (max_symlink_hops, MAX_SYMLINK_HOPS, "symlink_hops"),
    ):
        _need(type(value) is int and 0 <= value <= maximum,
              "external_tree_invalid_" + name + "_bound")
    raw = os.fspath(path)
    _need(type(raw) is str and raw and "\x00" not in raw,
          "external_tree_path_invalid")
    root = Path(raw)
    _need(root.is_absolute() and str(root) == raw and ".." not in root.parts
          and len(root.parts) <= MAX_DEPTH + 1
          and len(os.fsencode(raw)) <= MAX_PATH_BYTES,
          "external_tree_root_path_not_canonical")
    bounds = {
        "max_entries": max_entries,
        "max_bytes": max_bytes,
        "max_depth": max_depth,
        "max_symlink_hops": max_symlink_hops,
        "max_path_bytes": MAX_PATH_BYTES,
        "max_link_target_bytes": MAX_LINK_TARGET_BYTES,
        "max_serialized_bytes": MAX_SERIALIZED_BYTES,
        "max_resolution_steps": 4 * (max_entries + 1)
                                * (max_depth + max_symlink_hops + 1),
    }
    manifest = _opaque_manifest(opaque_symlinks, bounds)
    return _Observation(root, bounds, manifest).run()
