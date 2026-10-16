#!/usr/bin/env python3
"""Bounded private controller for one actual in-process registration owner.

The literal Popen child starts its own session and acquires its own original
scope. This controller passes pinned requests, never a lease or capability.
Private logs remain outside the native attempt; only that child may register.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import site
import stat
import subprocess
import sys
import time
import types

MAX_LOG_BYTES = 8 * 1024**2


def need(value, message):
    if not value:
        raise ValueError(message)


def stable_identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_uid,
            info.st_gid, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def registration_environment(cwd, inherited=None):
    """Select source/user-site search paths without executing user .pth files."""
    root = str(Path(__file__).absolute().parents[4])
    need(type(cwd) is str and Path(cwd).is_absolute(), "explicit source cwd required")
    user_site = site.getusersitepackages()
    need(type(user_site) is str and Path(user_site).is_absolute() and Path(user_site).is_dir(),
         "existing explicit user-site search directory required")
    search = list(dict.fromkeys([root, cwd, user_site]))
    env = dict(os.environ if inherited is None else inherited)
    env.update(PYTHONPATH=os.pathsep.join(search), PYTHONNOUSERSITE="1",
        PYTHONDONTWRITEBYTECODE="1", IPFS_DATASETS_PY_MINIMAL_IMPORTS="1",
        IPFS_DATASETS_AUTO_INSTALL="0", IPFS_AUTO_INSTALL="false",
        HF_HUB_OFFLINE="1", HF_DATASETS_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
        TOKENIZERS_PARALLELISM="false")
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                 "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "RAYON_NUM_THREADS"):
        env[name] = "1"
    return env


def initial_entry(path, expected):
    """Authenticate the small launch descriptor before executing stdlib entry helpers."""
    path = Path(path)
    need(path.is_absolute() and path.resolve(strict=True) == path, "canonical launch request required")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= 1024**2,
             "bounded launch request required")
        raw = os.read(fd, before.st_size + 1)
        need(len(raw) == before.st_size and hashlib.sha256(raw).hexdigest() == expected
             and stable_identity(os.fstat(fd)) == stable_identity(before)
             and stable_identity(path.stat()) == stable_identity(before), "launch request hash/identity differs")
    finally:
        os.close(fd)
    def pairs(items):
        out = {}
        for key, value in items:
            need(key not in out, "duplicate launch field")
            out[key] = value
        return out
    request = json.loads(raw, object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    pin = request["entry_pin"]
    need(type(pin) is dict and set(pin) == {"path", "bytes", "sha256"}
         and type(pin["bytes"]) is int and 0 < pin["bytes"] <= 4 * 1024**2,
         "bounded pinned entry required")
    entry = Path(pin["path"])
    need(entry.is_absolute() and entry.resolve(strict=True) == entry, "direct entry required")
    fd = os.open(entry, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size == pin["bytes"],
             "entry regular-byte identity differs")
        blocks, count = [], 0
        while True:
            block = os.read(fd, min(65536, pin["bytes"] + 1 - count))
            if not block:
                break
            count += len(block)
            need(count <= pin["bytes"], "entry grew")
            blocks.append(block)
        body = b"".join(blocks)
        need(count == pin["bytes"] and hashlib.sha256(body).hexdigest() == pin["sha256"]
             and stable_identity(os.fstat(fd)) == stable_identity(before)
             and stable_identity(entry.stat()) == stable_identity(before), "entry hash/identity differs")
    finally:
        os.close(fd)
    module = types.ModuleType("_checked_registration_controller_entry")
    module.__file__ = str(entry)
    exec(compile(body, str(entry), "exec", dont_inherit=True), module.__dict__)
    return module


def process_row(pid):
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
        fields = raw[raw.rfind(")") + 2:].split()
        return {"pid": pid, "state": fields[0], "parent": int(fields[1]), "group": int(fields[2]),
                "session": int(fields[3]), "birth": int(fields[19]), "uid": Path(f"/proc/{pid}").stat().st_uid}
    except FileNotFoundError:
        return None


def group_members(process, birth):
    leader = process_row(process.pid)
    if leader is not None:
        need(leader["birth"] == birth and leader["group"] == process.pid
             and leader["session"] == process.pid and leader["uid"] == os.getuid(),
             "original controller-owned process group substituted")
    members = []
    for item in Path("/proc").iterdir():
        if not item.name.isdecimal():
            continue
        row = process_row(int(item.name))
        if row is not None and row["group"] == process.pid and row["state"] != "Z":
            need(row["session"] == process.pid and row["uid"] == os.getuid(), "foreign process group member refused")
            members.append(row)
    return members


def drain_group(process, birth):
    sent = []
    for sig, seconds in ((signal.SIGINT, 2), (signal.SIGTERM, 3), (signal.SIGKILL, 5)):
        if not group_members(process, birth):
            break
        try:
            os.killpg(process.pid, sig)
            sent.append(sig.name)
        except ProcessLookupError:
            break
        until = time.monotonic() + seconds
        while time.monotonic() < until and group_members(process, birth):
            time.sleep(0.1)
    process.wait(timeout=5)
    need(not group_members(process, birth), "owned process group did not drain")
    return sent


def log_pin(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, "private log must remain regular")
        if before.st_size > MAX_LOG_BYTES:
            return {"path": str(path), "bytes": before.st_size, "sha256": None,
                    "unhashed_due_to_log_bound": True}
        digest, count = hashlib.sha256(), 0
        while True:
            block = os.read(fd, min(65536, MAX_LOG_BYTES + 1 - count))
            if not block:
                break
            count += len(block)
            need(count <= MAX_LOG_BYTES, "private log grew beyond bound")
            digest.update(block)
        need(count == before.st_size and stable_identity(os.fstat(fd)) == stable_identity(before)
             and stable_identity(path.stat()) == stable_identity(before),
             "private log changed while closing")
        return {"path": str(path), "bytes": count, "sha256": digest.hexdigest()}
    finally:
        os.close(fd)


def launch(path, expected):
    entry = initial_entry(path, expected)
    request, resource, _, launch_witness, captured = entry.load_request(path, expected)
    own = entry.direct(Path(__file__).absolute())
    own_digest = resource["source_sha256"].get(str(own))
    need(type(own_digest) is str, "launcher source must be included in native cohort")
    own_pin = {"path": str(own), "bytes": own.stat().st_size, "sha256": own_digest}
    own_raw, own_witness = entry.read_pin(own_pin)
    private = Path(request["private_output_directory"])
    need(not list(private.iterdir()), "exclusive empty private controller directory required")
    private_witness = entry.identity(private.stat())
    stdout, stderr = private / "entry.stdout.json", private / "entry.stderr.txt"
    summary_path = private / "launcher-result.json"
    summary = {"schema": "legal-ir-missing-component-launch-result/v1", "complete": False,
        "launch_request_sha256": expected, "original_grant_creation_location": "actual_entry_process_only",
        "original_grant_acquired_by_controller": False,
        "serialized_resource_capability_used": False, "retry_performed": False,
        "timed_out": False, "signals_sent": []}
    process = None
    birth = None
    out_fd = err_fd = None
    started = time.monotonic()
    try:
        out_fd = os.open(stdout, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        err_fd = os.open(stderr, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        entry.fence(request, launch_witness, captured)
        env = registration_environment(resource["cwd"])
        process = subprocess.Popen([sys.executable, "-B", request["entry_pin"]["path"],
            "--launch-request", str(path), "--expected-launch-request-sha256", expected],
            cwd=resource["cwd"], env=env, stdin=subprocess.DEVNULL, stdout=out_fd, stderr=err_fd,
            start_new_session=True)
        row = process_row(process.pid)
        need(row is not None and row["parent"] == os.getpid() and row["group"] == process.pid
             and row["session"] == process.pid, "literal direct child/session birth required")
        birth = row["birth"]
        while process.poll() is None:
            if time.monotonic() - started > request["timeout_seconds"]:
                summary["timed_out"] = True
                raise TimeoutError("controller deadline exceeded")
            need(os.fstat(out_fd).st_size <= MAX_LOG_BYTES and os.fstat(err_fd).st_size <= MAX_LOG_BYTES,
                 "private controller log exceeded bound")
            time.sleep(0.2)
        summary["child_returncode"] = process.wait(timeout=5)
        if group_members(process, birth):
            raise RuntimeError("owner exited with live descendants")
        need(summary["child_returncode"] == 0, "registration entry refused")
        entry.fence(request, launch_witness, captured)
        need(entry.read_pin(own_pin) == (own_raw, own_witness), "launcher source changed")
        need(entry.identity(entry.direct(private, directory=True).stat())[:6] == private_witness[:6],
             "private controller directory substituted")
        terminal = entry.decode(stdout.read_bytes())
        need(terminal.get("schema") == "legal-ir-missing-component-entry-terminal/v1"
             and terminal.get("complete") is True
             and terminal.get("resource_observation", {}).get("finalized") is True,
             "successful explicit native finalization required")
        summary.update(complete=True, entry_terminal=terminal, closing_input_fences_completed=True)
    except BaseException as error:
        summary["failure_type"] = type(error).__name__
    finally:
        if process is not None:
            try:
                if birth is None:
                    # Birth validation failed: never signal an unverified group.
                    process.wait(timeout=5)
                    summary["group_cleanup_not_authorized"] = True
                elif process.poll() is None or group_members(process, birth):
                    summary["signals_sent"] = drain_group(process, birth)
                else:
                    process.wait(timeout=5)
                summary["child_returncode"] = process.returncode
                summary["owned_group_drained"] = birth is not None and not group_members(process, birth)
            except BaseException as error:
                summary["complete"] = False
                summary["cleanup_failure_type"] = type(error).__name__
        for fd in (out_fd, err_fd):
            if fd is not None:
                try:
                    os.fsync(fd)
                    observed_path = stdout if fd == out_fd else stderr
                    need(entry.identity(observed_path.lstat()) == entry.identity(os.fstat(fd)),
                         "controller log path substituted")
                finally:
                    os.close(fd)
    summary["elapsed_seconds"] = time.monotonic() - started
    summary["logs"] = [log_pin(p) for p in (stdout, stderr) if p.exists()]
    need(entry.identity(entry.direct(private, directory=True).stat())[:6] == private_witness[:6],
         "private controller directory substituted before publication")
    raw = entry.wire(summary) + b"\n"
    need(len(raw) <= MAX_LOG_BYTES, "private final aggregate exceeds bound")
    fd = os.open(summary_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(private, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    print(entry.wire({"complete": summary["complete"], "private_launcher_result_pin":
        {"path": str(summary_path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}}).decode())
    return 0 if summary["complete"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launch-request", required=True)
    parser.add_argument("--expected-launch-request-sha256", required=True)
    args = parser.parse_args()
    os.umask(0o077)
    raise SystemExit(launch(args.launch_request, args.expected_launch_request_sha256))


if __name__ == "__main__":
    main()
