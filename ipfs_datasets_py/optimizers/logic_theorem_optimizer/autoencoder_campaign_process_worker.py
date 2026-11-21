"""Direct-file, stdlib-only bootstrap for fixed original campaign jobs.

The owner launches with -I -S. Network denial precedes site/package imports;
the waiting child cannot load a job or construct weights before owner release.
The selected fixed job owner remains the only producer of receipt.json.
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


def _network_denial(expected_sha256, *, fixed_seccomp=False):
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
    return module._deny_network(fixed_seccomp=True) if fixed_seccomp else module._deny_network()


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


def _reviewed_dependency_prefix(parent_prefix, *, restore=False):
    """Bind dependency discovery to this executable's original lexical prefix."""
    _require(type(restore) is bool, "explicit dependency prefix restoration mode required")
    _require(type(parent_prefix) is str, "explicit original Python dependency prefix required")
    prefix = Path(parent_prefix)
    _require(prefix.is_absolute() and str(prefix) == parent_prefix and ".." not in prefix.parts
             and prefix == Path(sys.executable).parent.parent,
             "original Python dependency prefix differs from this executable")
    for component in reversed((prefix, *prefix.parents)):
        info = component.lstat()
        _require(stat.S_ISDIR(info.st_mode) and info.st_uid in {0, os.getuid()},
                 "original Python dependency prefix has an unsafe component")
    # Debian site.py distinguishes venv site-packages from dist-packages via
    # this metadata even when explicit prefixes are supplied under -I -S.
    # Restore only the validated original prefix; never run site.main/.pth.
    if restore:
        sys.prefix = parent_prefix
        sys.exec_prefix = parent_prefix
    return parent_prefix


def _reviewed_dependency_paths(parent_prefix, parent_paths=None):
    """Capture/validate only active known site roots; never execute site hooks."""
    import site
    prefix = _reviewed_dependency_prefix(parent_prefix)
    primary = site.getsitepackages(prefixes=[prefix])
    known = [*primary, site.getusersitepackages(),
        *site.getsitepackages(prefixes=[sys.base_prefix, sys.base_exec_prefix])]
    if parent_paths is None:
        paths = list(dict.fromkeys(value for value in sys.path if type(value) is str and value in known))
    else:
        _require(type(parent_paths) is list, "bounded original dependency directory list required")
        paths = list(parent_paths)
    _require(1 <= len(paths) <= 8 and all(type(value) is str and value in known for value in paths)
             and len(paths) == len(set(paths)), "unknown or repeated original dependency directory")
    raw = json.dumps(paths, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    _require(len(raw) <= 4096, "original dependency directory profile exceeds bound")
    for value in paths:
        path = Path(value)
        _require(path.is_absolute() and str(path) == value and ".." not in path.parts,
                 "original dependency directory is not canonical")
        for component in reversed((path, *path.parents)):
            info = component.lstat()
            _require(stat.S_ISDIR(info.st_mode) and info.st_uid in {0, os.getuid()},
                     "original dependency directory has an unsafe component")
    return tuple(paths)


def _configure_dependency_paths(*, parent_prefix=None, parent_paths=None):
    # Importing stdlib site under -S is inert. Discover directories without
    # executing .pth files, editable finders, sitecustomize or usercustomize.
    import site
    if parent_prefix is None:
        _require(parent_paths is None, "dependency directory profile requires its original prefix")
        candidates = [site.getusersitepackages(), *site.getsitepackages()]
    elif parent_paths is None:
        prefix = _reviewed_dependency_prefix(parent_prefix, restore=True)
        candidates = site.getsitepackages(prefixes=[prefix])
    else:
        prefix = _reviewed_dependency_prefix(parent_prefix, restore=True)
        candidates = _reviewed_dependency_paths(prefix, parent_paths)
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
    raw = verify({"path": path, "sha256": expected_sha256, "bytes": byte_count}, 64 * 1024 * 1024)
    payload = parse_json(raw)
    if type(payload) is dict and payload.get("schema_version") == "legal-ir-f18-conditions-training-job/v1":
        # This import is deliberately after the unchanged offline/owner RUN
        # handshake in main. Neither arbitrary modules nor worker callbacks
        # can be selected by the serialized request.
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_campaign_f18_conditions_v1 import (
            SCHEMA_VERSION, F18JobSpec, execute_job,
        )
        spec = F18JobSpec.from_dict(payload)
        _require(spec.to_dict()["schema_version"] == SCHEMA_VERSION and spec.canonical_sha256 == spec_sha256,
                 "fixed F18 job identity differs")
        _require(not defer_gc and not reduce_targets and spec.legal_ir_parallel_workers == 1,
                 "unsupported fixed F18 execution policy")
        execute_job(spec, job_file_sha256=expected_sha256)
        return
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import (
        CAMPAIGN_SCHEMA_VERSION, TrainingJobSpec, _execute_training_job,
    )
    spec = TrainingJobSpec.from_dict(payload)
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




_REVIEWED_CALLBACK_REQUEST = "reviewed-parent-callback-request/v1"
_REVIEWED_CALLBACK_REPLY = "reviewed-parent-callback-reply/v1"
_REVIEWED_CALLBACK_READY = "reviewed-source-evaluation-ready/v1"
_REVIEWED_CALLBACK_MAX_REQUEST = 32 * 1024
_REVIEWED_CALLBACK_MAX_REPLY = 1024


def _reviewed_callback_identity(value):
    _require(type(value) is dict and set(value) == {"pid", "birth"}
             and type(value["pid"]) is int and value["pid"] > 0
             and type(value["birth"]) is str and 0 < len(value["birth"]) <= 32
             and value["birth"].isascii() and value["birth"].isdigit() and int(value["birth"]) > 0,
             "exact reviewed callback process identity required")
    return dict(value)


def _reviewed_callback_digest(value):
    _require(type(value) is str and len(value) == 64
             and all(character in "0123456789abcdef" for character in value),
             "exact reviewed callback SHA256 required")
    return value


def _reviewed_callback_encode(value, maximum):
    count = 0
    def visit(item, depth=0):
        nonlocal count
        count += 1
        _require(count <= 4096 and depth <= 32, "reviewed callback JSON structure exceeds bound")
        if type(item) is dict:
            _require(all(type(key) is str for key in item), "ordinary callback JSON keys required")
            for child in item.values():
                visit(child, depth + 1)
        elif type(item) is list:
            for child in item:
                visit(child, depth + 1)
        else:
            _require(item is None or type(item) in (str, int, bool)
                     or type(item) is float and math.isfinite(item), "ordinary finite callback JSON required")
    visit(value)
    raw = json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                     separators=(",", ":")).encode("utf-8") + b"\n"
    _require(len(raw) <= maximum, "reviewed callback frame exceeds bound")
    return raw


def _reviewed_callback_decode(raw, maximum):
    _require(type(raw) is bytes and 0 < len(raw) <= maximum
             and raw.endswith(b"\n") and raw.count(b"\n") == 1,
             "one bounded reviewed callback frame required")
    def pairs(values):
        result = {}
        for key, value in values:
            _require(key not in result, "duplicate reviewed callback JSON member")
            result[key] = value
        return result
    def nonfinite(value):
        raise RuntimeError("nonfinite reviewed callback JSON")
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)
    _reviewed_callback_encode(value, maximum)
    return value


def _reviewed_callback_process(pid):
    try:
        raw = Path("/proc", str(pid), "stat").read_text()
    except FileNotFoundError:
        return None
    fields = raw[raw.rfind(")") + 2:].split()
    _require(len(fields) >= 22, "reviewed callback process observation is malformed")
    if fields[0] in ("Z", "X", "x"):
        return None
    return {"pid": pid, "birth": fields[19], "parent_pid": int(fields[1]),
            "group_pid": int(fields[2])}


def _reviewed_callback_await_run(fd, *, owner_identity, deadline):
    token = b""
    while len(token) < 4:
        parent = _reviewed_callback_process(owner_identity["pid"])
        _require(os.getppid() == owner_identity["pid"] and parent is not None
                 and {key: parent[key] for key in owner_identity} == owner_identity,
                 "original reviewed parent disappeared before RUN")
        remaining = deadline - time.monotonic()
        _require(remaining > 0, "original reviewed RUN deadline expired")
        if select.select([fd], [], [], min(remaining, .2))[0]:
            part = os.read(fd, 4 - len(token))
            _require(bool(part), "original reviewed parent closed RUN before release")
            token += part
    _require(token == b"RUN\n", "invalid original reviewed RUN token")


class _ReviewedParentCallbackClient:
    """An inherited private channel, never a serialized grant or a new owner.

    The original parent owns native/storage/Source custody. Every successful
    exchange observes its live checks for this one child and sequence only.
    The caller transfers ownership of this RPC descriptor on construction;
    close never touches the separate retained RUN/revocation descriptor.
    """

    def __init__(self, fd, *, owner_identity, child_identity, request_sha256, deadline):
        _require(type(fd) is int and fd >= 3, "inherited reviewed callback descriptor required")
        info = os.fstat(fd)
        _require(stat.S_ISSOCK(info.st_mode), "reviewed callback requires an inherited socket endpoint")
        self._owner = _reviewed_callback_identity(owner_identity)
        self._child = _reviewed_callback_identity(child_identity)
        self._request = _reviewed_callback_digest(request_sha256)
        _require(type(deadline) in (int, float) and math.isfinite(deadline)
                 and 0 < deadline - time.monotonic() <= 86400,
                 "original absolute reviewed callback deadline required")
        self._deadline = deadline
        self._fd = fd
        self._fd_identity = (info.st_dev, info.st_ino, info.st_mode)
        self._sequence = 0
        self._closed = False
        self._finished = False
        self._lock = threading.Lock()
        self._record = {"schema": "reviewed-parent-callback-client-observation/v1",
            "completed_requests": 0, "operations": {"GUARD": 0, "ASSET": 0, "ADMISSION": 0, "FINISH": 0},
            "last_error": None, "resource_authority_granted": False, "storage_release_authorized": False}
        os.set_blocking(fd, False)
        os.set_inheritable(fd, False)

    def _current(self):
        _require(not self._closed and time.monotonic() < self._deadline,
                 "original reviewed callback deadline expired or channel closed")
        info = os.fstat(self._fd)
        _require((info.st_dev, info.st_ino, info.st_mode) == self._fd_identity,
                 "reviewed callback descriptor identity changed")
        parent = _reviewed_callback_process(self._owner["pid"])
        child = _reviewed_callback_process(self._child["pid"])
        _require(os.getpid() == self._child["pid"] and os.getppid() == self._owner["pid"]
                 and parent is not None and child is not None
                 and {key: parent[key] for key in self._owner} == self._owner
                 and {key: child[key] for key in self._child} == self._child
                 and child["parent_pid"] == self._owner["pid"]
                 and child["group_pid"] == child["pid"],
                 "original reviewed callback parent/child process binding changed")

    def _wait(self, *, write=False):
        self._current()
        remaining = self._deadline - time.monotonic()
        readable, writable, _ = select.select([] if write else [self._fd],
            [self._fd] if write else [], [], min(remaining, .2))
        self._current()
        return bool(writable if write else readable)

    def _exchange(self, operation, payload):
        acquired = False
        try:
            remaining = self._deadline - time.monotonic()
            acquired = remaining > 0 and self._lock.acquire(timeout=remaining)
            _require(acquired, "original reviewed callback deadline expired waiting for its one exchange")
            self._current()
            _require(operation in ("GUARD", "ASSET", "ADMISSION", "TRAIN_ADMISSION", "CONTEXT", "FINISH"),
                     "unsupported reviewed callback operation")
            if operation in ("GUARD", "FINISH"):
                _require(payload is None, "GUARD/FINISH callback accepts no payload")
            elif operation in ("ASSET", "CONTEXT"):
                _require(type(payload) is dict, "ordinary " + operation + " policy callback payload required")
            else:
                _require(type(payload) is dict and set(payload) == {"expected_sha256"},
                         operation + " callback accepts only its expected digest")
                _reviewed_callback_digest(payload["expected_sha256"])
            sequence = self._sequence + 1
            _require(sequence <= 2**31 - 1, "reviewed callback sequence exhausted")
            frame = {"schema": _REVIEWED_CALLBACK_REQUEST, "request_sha256": self._request,
                "sequence": sequence, "operation": operation, "owner_identity": self._owner,
                "child_identity": self._child, "payload": payload}
            raw = _reviewed_callback_encode(frame, _REVIEWED_CALLBACK_MAX_REQUEST)
            offset = 0
            while offset < len(raw):
                if not self._wait(write=True):
                    continue
                try:
                    written = os.write(self._fd, raw[offset:])
                except BlockingIOError:
                    continue
                _require(written > 0, "original parent callback write closed")
                offset += written
            reply = b""
            while b"\n" not in reply:
                if not self._wait():
                    continue
                try:
                    chunk = os.read(self._fd, _REVIEWED_CALLBACK_MAX_REPLY + 1 - len(reply))
                except BlockingIOError:
                    continue
                _require(bool(chunk), "original parent callback closed without acknowledgement")
                reply += chunk
                _require(len(reply) <= _REVIEWED_CALLBACK_MAX_REPLY, "reviewed callback reply exceeds bound")
            value = _reviewed_callback_decode(reply, _REVIEWED_CALLBACK_MAX_REPLY)
            _require(type(value) is dict and set(value) == {"schema", "request_sha256", "sequence",
                "operation", "owner_identity", "child_identity", "admission_sha256"}
                and value["schema"] == _REVIEWED_CALLBACK_REPLY
                and value["request_sha256"] == self._request and type(value["sequence"]) is int
                and value["sequence"] == sequence and value["operation"] == operation
                and _reviewed_callback_identity(value["owner_identity"]) == self._owner
                and _reviewed_callback_identity(value["child_identity"]) == self._child,
                "original parent callback acknowledgement binding differs")
            if operation in ("ADMISSION", "TRAIN_ADMISSION"):
                _require(_reviewed_callback_digest(value["admission_sha256"]) == payload["expected_sha256"],
                         "parent current admission digest differs")
            else:
                _require(value["admission_sha256"] is None, "unexpected admission data in callback acknowledgement")
            self._current()
            self._sequence = sequence
            self._record["completed_requests"] += 1
            operations = self._record["operations"]
            operations[operation] = operations.get(operation, 0) + 1
            if operation == "FINISH":
                self._finished = True
                self.close()
            return value["admission_sha256"]
        except BaseException as error:
            self._record["last_error"] = {"type": type(error).__name__, "message": str(error)[:512]}
            self.close()
            raise
        finally:
            if acquired:
                self._lock.release()

    def execution_guard(self):
        self._exchange("GUARD", None)

    def asset_policy_guard(self, policy):
        self._exchange("ASSET", policy)

    def current_admission_digest(self, expected_sha256):
        return self._exchange("ADMISSION", {"expected_sha256": expected_sha256})

    def current_training_admission_digest(self, expected_sha256):
        return self._exchange("TRAIN_ADMISSION", {"expected_sha256": expected_sha256})

    def context_policy_guard(self, policy):
        self._exchange("CONTEXT", policy)

    def finish(self):
        self._exchange("FINISH", None)

    def close(self):
        if not self._closed:
            self._closed = True
            try:
                info = os.fstat(self._fd)
            except OSError:
                self._record["rpc_descriptor_closed_elsewhere"] = True
                return
            if (info.st_dev, info.st_ino, info.st_mode) != self._fd_identity:
                self._record["rpc_descriptor_identity_changed"] = True
                return
            os.close(self._fd)

    def observation(self):
        return json.loads(json.dumps({**self._record, "closed": self._closed,
            "finished": self._finished,
            "request_sha256": self._request, "last_sequence": self._sequence,
            "owner_identity": self._owner, "child_identity": self._child,
            "original_deadline_monotonic": self._deadline}, sort_keys=True, allow_nan=False))


def _reviewed_evaluation_main(argv):
    """Fixed offline evaluation bootstrap; the original v8 main is unchanged."""
    _require(len(argv) == 12, "reviewed evaluation bootstrap requires twelve fixed arguments")
    path, digest, byte_count, ready_fd, release_fd, callback_fd, owner_pid, owner_birth, deadline, network_sha, parent_prefix, parent_paths_raw = argv
    byte_count, ready_fd, release_fd, callback_fd, owner_pid = map(int,
        (byte_count, ready_fd, release_fd, callback_fd, owner_pid))
    deadline = float(deadline)
    _require(sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode
             and 0 < byte_count <= 1024**2 and len({ready_fd, release_fd, callback_fd}) == 3
             and min(ready_fd, release_fd, callback_fd) >= 3,
             "isolated reviewed evaluation descriptors/byte bound required")
    parent_prefix = _reviewed_dependency_prefix(parent_prefix, restore=True)
    _require(type(parent_paths_raw) is str and len(parent_paths_raw.encode("utf-8")) <= 4096,
             "bounded original dependency directory DATA required")
    parent_paths = _reviewed_dependency_paths(parent_prefix, json.loads(parent_paths_raw))
    owner_identity = _reviewed_callback_identity({"pid": owner_pid, "birth": owner_birth})
    _reviewed_callback_digest(digest)
    _require(type(path) is str and Path(path).is_absolute() and math.isfinite(deadline)
             and 0 < deadline - time.monotonic() <= 86400,
             "original reviewed evaluation path/deadline required")
    _require(not any(name == "ipfs_datasets_py" or name.startswith("ipfs_datasets_py.")
                     for name in sys.modules), "reviewed evaluation package imported before offline bootstrap")
    sys.path.insert(0, str(ROOT))
    network_guard = _network_denial(network_sha, fixed_seccomp=True)
    identity = _identity()
    parent = _reviewed_callback_process(owner_pid)
    _require(identity["pid"] == identity["group_pid"] and os.getppid() == owner_pid
             and parent is not None and {key: parent[key] for key in owner_identity} == owner_identity,
             "reviewed evaluation original parent/isolated child differs")
    _send_ready(ready_fd, {"schema": _REVIEWED_CALLBACK_READY, "identity": identity,
        "owner_pid": owner_pid, "owner_birth": owner_birth, "request_sha256": digest,
        "canonical_root": str(ROOT), "network_guard": network_guard,
        "python_dependency_prefix": parent_prefix, "python_dependency_paths": list(parent_paths)})
    os.close(ready_fd)
    _reviewed_callback_await_run(release_fd, owner_identity=owner_identity, deadline=deadline)
    watcher = threading.Thread(target=_watch_owner,
        kwargs={"fd": release_fd, "owner_pid": owner_pid, "group_pid": identity["group_pid"]}, daemon=True)
    watcher.start()
    client = _ReviewedParentCallbackClient(callback_fd, owner_identity=owner_identity,
        child_identity={key: identity[key] for key in ("pid", "birth")},
        request_sha256=digest, deadline=deadline)
    try:
        client.execution_guard()
        _configure_dependency_paths(parent_prefix=parent_prefix, parent_paths=list(parent_paths))
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_inference import _execute_reviewed_evaluation_request
        _execute_reviewed_evaluation_request({"path": path, "sha256": digest, "bytes": byte_count}, parent_client=client)
        client.finish()
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    if sys.argv[1:2] == ["--reviewed-source-evaluation"]:
        try:
            reviewed_exit = _reviewed_evaluation_main(sys.argv[2:])
        except BaseException as error:
            print("reviewed evaluation worker failed: " + type(error).__name__ + ": " + str(error)[:2048], file=sys.stderr)
            import traceback
            rendered = "".join(traceback.TracebackException.from_exception(
                error, limit=12, capture_locals=False).format(chain=False))
            bounded = rendered.encode("utf-8", errors="replace")[:8192].decode("utf-8", errors="ignore")
            print(bounded, end="", file=sys.stderr)
            reviewed_exit = 1
        raise SystemExit(reviewed_exit)
    raise SystemExit(main())
