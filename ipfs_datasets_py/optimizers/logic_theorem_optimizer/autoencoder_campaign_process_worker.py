"""Direct-file, stdlib-only bootstrap for an original v8 campaign worker.

The owner launches with -I -S. Network denial precedes site/package imports;
the waiting child cannot load a job or construct weights before owner release.
The ordinary worker remains the only producer of receipt.json.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import select
import signal
import stat
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[3]
NETWORK_SCRIPT = Path(__file__).with_name("autoencoder_daemon_invocation_worker.py")
MAX_READY_BYTES = 8192


def _require(condition, message):
    if not condition:
        raise RuntimeError(message)


def _network_denial(expected_sha256):
    # Direct-file import avoids running ipfs_datasets_py package ancestors.
    def read_source():
        fd = os.open(NETWORK_SCRIPT, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            _require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), "network bootstrap is not regular")
            raw = stream.read(1024 * 1024 + 1)
        _require(len(raw) <= 1024 * 1024, "network bootstrap exceeds source bound")
        return raw
    raw = read_source()
    _require(hashlib.sha256(raw).hexdigest() == expected_sha256,
             "network bootstrap source differs")
    spec = importlib.util.spec_from_file_location("_campaign_offline_network_bootstrap", NETWORK_SCRIPT)
    _require(spec is not None and spec.loader is not None, "network bootstrap is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _require(read_source() == raw, "network bootstrap changed during import")
    return module._deny_network()


def _identity():
    raw = Path("/proc/self/stat").read_text()
    fields = raw[raw.rfind(")") + 2:].split()
    _require(len(fields) >= 22, "invalid child process identity")
    return {"pid": os.getpid(), "group_pid": int(fields[2]), "birth": fields[19]}


def _send_ready(fd, payload):
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    _require(len(raw) <= MAX_READY_BYTES, "ready payload exceeds bound")
    offset = 0
    while offset < len(raw):
        written = os.write(fd, raw[offset:])
        _require(written > 0, "ready pipe closed")
        offset += written


def _await_release(fd, *, timeout_seconds, owner_pid):
    deadline = time.monotonic() + timeout_seconds
    token = b""
    while len(token) < 4:
        _require(os.getppid() == owner_pid, "owner disappeared before compute release")
        remaining = deadline - time.monotonic()
        _require(remaining > 0, "compute release deadline expired")
        readable, _, _ = select.select([fd], [], [], min(remaining, 0.2))
        if readable:
            chunk = os.read(fd, 4 - len(token))
            _require(bool(chunk), "owner closed compute release pipe")
            token += chunk
    _require(token == b"RUN\n", "invalid compute release token")


def _watch_owner(fd, *, owner_pid, group_pid):
    # A fresh session makes this group private to this bootstrap. Unexpected
    # bytes or EOF revoke execution; killing the group also stops descendants.
    while True:
        try:
            readable, _, _ = select.select([fd], [], [], 0.2)
            gone = os.getppid() != owner_pid or bool(readable)
        except BaseException:
            gone = True
        if gone:
            if os.getpid() == group_pid and os.getpgrp() == group_pid:
                os.killpg(group_pid, signal.SIGKILL)
            os._exit(124)


def _configure_dependency_paths():
    # Importing stdlib site under -S is inert. Discover directories without
    # executing .pth files, editable finders, sitecustomize or usercustomize.
    import site
    candidates = [site.getusersitepackages(), *site.getsitepackages()]
    paths = []
    for value in candidates:
        path = Path(value)
        _require(path.is_absolute() and str(path) == value and ".." not in path.parts,
                 "dependency directory is not canonical")
        missing = False
        for component in reversed((path, *path.parents)):
            try:
                info = component.lstat()
            except FileNotFoundError:
                missing = True
                break
            _require(stat.S_ISDIR(info.st_mode) and info.st_uid in {0, os.getuid()},
                     "dependency directory has an unsafe component")
        if not missing and value not in paths:
            paths.append(value)
    sys.path[:] = [str(ROOT), *[value for value in sys.path
                              if value != str(ROOT) and value not in paths], *paths]
    return tuple(paths)


def _run_original(path, expected_sha256, byte_count, spec_sha256, *, defer_gc, reduce_targets):
    # Discovery follows the irreversible network filter and owner handshake.
    _configure_dependency_paths()
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    require_workspace_logic_tree()
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_invocation_contracts import parse_json, verify
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import (
        CAMPAIGN_SCHEMA_VERSION, TrainingJobSpec, _execute_training_job,
    )
    raw = verify({"path": path, "sha256": expected_sha256, "bytes": byte_count}, 64 * 1024 * 1024)
    spec = TrainingJobSpec.from_dict(parse_json(raw))
    _require(spec.schema_version == CAMPAIGN_SCHEMA_VERSION and spec.canonical_sha256 == spec_sha256,
             "original campaign job identity differs")
    _execute_training_job(spec, trainer=None, job_file_sha256=expected_sha256,
                         defer_target_hydration_gc=defer_gc, reduce_native_targets=reduce_targets)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 11:
        print("invalid original campaign worker arguments", file=sys.stderr)
        return 2
    try:
        path, sha256, byte_count, spec_sha256, ready_fd, release_fd, owner_pid, timeout, source_sha, defer_gc, reduce = argv
        byte_count, ready_fd, release_fd, owner_pid = map(int, (byte_count, ready_fd, release_fd, owner_pid))
        timeout = float(timeout)
        _require(math.isfinite(timeout) and 0 < timeout <= 30 and 0 < byte_count <= 64 * 1024 * 1024,
                 "invalid bootstrap limits")
        _require(ready_fd >= 3 and release_fd >= 3 and ready_fd != release_fd and owner_pid > 0,
                 "invalid bootstrap descriptors")
        _require(defer_gc in {"0", "1"} and reduce in {"0", "1"}, "invalid execution policy")
        _require(sys.flags.isolated and sys.flags.no_site, "worker requires an isolated no-site bootstrap")
        _require(not any(key == "ipfs_datasets_py" or key.startswith("ipfs_datasets_py.")
                         for key in sys.modules), "package imported before offline bootstrap")
        sys.path.insert(0, str(ROOT))
        guard = _network_denial(source_sha)
        identity = _identity()
        _require(identity["pid"] == identity["group_pid"] and os.getppid() == owner_pid,
                 "worker is not an owned isolated process group")
        _send_ready(ready_fd, {"schema": "autoencoder-campaign-process-ready-v1", "identity": identity,
            "owner_pid": owner_pid, "job_sha256": sha256, "canonical_root": str(ROOT), "network_guard": guard})
        os.close(ready_fd)
        _await_release(release_fd, timeout_seconds=timeout, owner_pid=owner_pid)
        watcher = threading.Thread(target=_watch_owner, kwargs={
            "fd": release_fd, "owner_pid": owner_pid, "group_pid": identity["group_pid"]}, daemon=True)
        watcher.start()
        _run_original(path, sha256, byte_count, spec_sha256, defer_gc=defer_gc == "1", reduce_targets=reduce == "1")
        return 0
    except BaseException as exc:
        # The bootstrap never manufactures an alternate successful worker receipt.
        print(f"campaign worker failed: {type(exc).__name__}: {str(exc)[:2048]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
