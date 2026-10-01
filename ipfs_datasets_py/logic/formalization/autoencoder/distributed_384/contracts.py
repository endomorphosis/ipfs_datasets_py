"""Portable identities and immutable bounded artifacts for distributed training."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid

MAX_BYTES = 64 * 1024 * 1024
DOMAINS = ("intent_ir", "security_ir", "ui_ux_ir", "legal_ir")
SHA = re.compile(r"[0-9a-f]{64}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
FALSE = dict(qualified=False, admitted=False, proof_authority=False,
             source_semantics_verified=False, promotion_performed=False)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(raw(value)).hexdigest()


def _parent_fd(path, *, create=False):
    """Anchor every directory component without following filesystem aliases."""
    path = Path(path).absolute()
    require(".." not in path.parts and path.name not in ("", ".", ".."), "plain artifact path required")
    fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.parent.parts[1:]:
            if create:
                try:
                    os.mkdir(component, dir_fd=fd)
                except FileExistsError:
                    pass
            following = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = following
        return path, fd
    except BaseException:
        os.close(fd)
        raise


def _read_at(directory, name, maximum):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= maximum,
                "bounded nonempty regular artifact required")
        data = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
        identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
        require(identity(before) == identity(after) and len(data) == before.st_size,
                "artifact changed during read")
    require(0 < len(data) <= maximum, "artifact exceeds bound")
    return data


def read_bound(path, *, maximum=MAX_BYTES):
    """Return (exact bytes, SHA256/size) from one bounded, no-follow file read."""
    require(type(maximum) is int and 0 < maximum <= MAX_BYTES, "invalid artifact byte bound")
    directory = None
    try:
        path, directory = _parent_fd(path)
        data = _read_at(directory, path.name, maximum)
        return data, {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    except OSError as exc:
        raise ValueError("artifact is missing, aliased or unreadable") from exc
    finally:
        if directory is not None:
            os.close(directory)


def file_ref(path):
    return read_bound(path)[1]


def _parse(data):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    def bad(value):
        raise ValueError("nonfinite JSON number")
    value = json.loads(data, object_pairs_hook=pairs, parse_constant=bad)
    raw(value)  # Also rejects finite-looking overflow literals, e.g. 1e999.
    return value


def read_json_bound(path):
    """Return (parsed JSON, file reference) bound to the same immutable read."""
    data, reference = read_bound(path)
    return _parse(data), reference


def read_json(path):
    return read_json_bound(path)[0]


def write_json(path, value):
    """Atomic, fsynced, create-only output; identical retries are idempotent."""
    path = Path(path).absolute()
    data = raw(value)
    require(0 < len(data) <= MAX_BYTES, "artifact exceeds bound")
    directory = None
    name = ".ir384-" + uuid.uuid4().hex
    created = False
    try:
        path, directory = _parent_fd(path, create=True)
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory)
        created = True
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(name, path.name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
        except FileExistsError:
            require(_read_at(directory, path.name, MAX_BYTES) == data, "immutable artifact conflicts")
        os.fsync(directory)
        # A parent-directory rename must not make the returned path name some
        # different file. Publication above always targets the anchored parent.
        require(read_bound(path)[0] == data, "published artifact path changed")
    except OSError as exc:
        raise ValueError("artifact destination is aliased or unavailable") from exc
    finally:
        if created:
            os.unlink(name, dir_fd=directory)
        if directory is not None:
            os.close(directory)
    return path


def binding(plan):
    return {key: plan[key] for key in ("plan_id", "domain_id", "base_checkpoint_sha256",
                                       "dataset_sha256", "recipe_sha256")}
