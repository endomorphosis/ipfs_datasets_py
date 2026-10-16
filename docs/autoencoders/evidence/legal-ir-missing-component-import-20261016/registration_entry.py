#!/usr/bin/env python3
"""Checked-source, same-process metadata registration; launched by its controller.

This file creates no borrowed/serialized resource capability. Its actual process
owns the original scope, imports no model payload and prints a private terminal
record only after the scope exits. No automatic retry or database rollback.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import types

SCHEMA = "legal-ir-missing-component-launch-request/v1"
META = Path("/home/barberb/lift_coding/artifacts/legal-ir-missing-component-import-20261016")
HEX = re.compile(r"[0-9a-f]{64}\Z")
PINS = ("entry_pin", "resource_scope_pin", "driver_pin", "resource_request_pin", "registration_request_pin")


def need(value, message):
    if not value:
        raise ValueError(message)


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def decode(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            need(key not in out, "duplicate JSON field")
            out[key] = value
        return out
    return json.loads(raw, object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def direct(path, *, directory=False):
    path = Path(path)
    need(path.is_absolute() and ".." not in path.parts, "absolute direct path required")
    for part in (*reversed(path.parents), path):
        info = part.lstat()
        need(not stat.S_ISLNK(info.st_mode), "symlink path refused")
        need(stat.S_ISDIR(info.st_mode) if part != path or directory else
             stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "direct directory/regular file required")
    return path


def identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_uid,
            info.st_gid, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def read_pin(pin, *, maximum=4 * 1024**2):
    need(type(pin) is dict and set(pin) == {"path", "bytes", "sha256"}, "closed file pin required")
    need(type(pin["path"]) is str and type(pin["bytes"]) is int and 0 < pin["bytes"] <= maximum
         and type(pin["sha256"]) is str and HEX.fullmatch(pin["sha256"]), "bounded exact input pin required")
    path = direct(pin["path"])
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        need(before.st_size == pin["bytes"] and identity(path.lstat()) == identity(before), "opening input differs")
        blocks, count = [], 0
        while True:
            block = os.read(fd, min(65536, pin["bytes"] + 1 - count))
            if not block:
                break
            count += len(block)
            need(count <= pin["bytes"], "input grew")
            blocks.append(block)
        raw = b"".join(blocks)
        need(count == pin["bytes"] and hashlib.sha256(raw).hexdigest() == pin["sha256"]
             and identity(os.fstat(fd)) == identity(before) and identity(path.lstat()) == identity(before),
             "stable input hash/identity required")
        return raw, identity(before)
    finally:
        os.close(fd)


def load_request(path, expected_sha256):
    need(type(expected_sha256) is str and HEX.fullmatch(expected_sha256), "independent launch request SHA required")
    path = direct(path)
    pin = {"path": str(path), "bytes": path.stat().st_size, "sha256": expected_sha256}
    raw, witness = read_pin(pin, maximum=1024**2)
    request = decode(raw)
    need(type(request) is dict and set(request) == {"schema", *PINS, "timeout_seconds", "private_output_directory"}
         and request["schema"] == SCHEMA, "closed launch request required")
    need(type(request["timeout_seconds"]) is int and 1 <= request["timeout_seconds"] <= 3600,
         "bounded launcher deadline required")
    captured = {key: read_pin(request[key]) for key in PINS}
    resource = decode(captured["resource_request_pin"][0])
    registration = decode(captured["registration_request_pin"][0])
    need(resource.get("schema") == "model-manager-metadata-registration-resource-request/v1"
         and registration.get("schema") == "legal-ir-missing-component-registration-request/v1",
         "selected registration/resource request schemas required")
    need(registration["resource_scope_pin"] == request["resource_scope_pin"], "scope source pin join differs")
    root = direct(resource["cwd"], directory=True)
    need(root == Path(registration["datasets_root"]) and root == Path(request["entry_pin"]["path"]).parents[4],
         "entry/current-source root join differs")
    need(resource["timeout_seconds"] <= request["timeout_seconds"], "outer deadline cannot understate native deadline")
    attempt = direct(resource["attempt_directory"], directory=True)
    need(Path(registration["output_directory"]) == attempt / "exports", "exact owned exports required")
    private = direct(request["private_output_directory"], directory=True)
    need(META in private.parents and attempt != private and attempt not in private.parents
         and stat.S_IMODE(private.stat().st_mode) == 0o700 and private.stat().st_uid == os.getuid(),
         "owned0700 private controller directory outside attempt required")
    need(attempt not in path.parents, "launch request cannot belong to mutable attempt")
    for key in ("entry_pin", "resource_scope_pin", "driver_pin"):
        need(resource["source_sha256"].get(request[key]["path"]) == request[key]["sha256"],
             "entry/scope/driver must belong to native source cohort")
    return request, resource, registration, (pin, witness), captured


def fence(request, launch_witness, captured):
    pin, witness = launch_witness
    _, current = read_pin(pin, maximum=1024**2)
    need(current == witness, "launch request identity changed")
    for key in PINS:
        raw, current = read_pin(request[key])
        need((raw, current) == captured[key], "launch input substituted")


def checked_module(name, pin, raw):
    need(name not in sys.modules, "checked module already present")
    module = types.ModuleType(name)
    module.__file__ = pin["path"]
    sys.modules[name] = module
    try:
        exec(compile(raw, pin["path"], "exec", dont_inherit=True), module.__dict__)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def run(path, expected):
    scope = None
    terminal = {"schema": "legal-ir-missing-component-entry-terminal/v1", "complete": False,
                "serialized_resource_capability_used": False, "retry_performed": False}
    try:
        request, resource, _, launch_witness, captured = load_request(path, expected)
        need(Path(__file__).absolute() == Path(request["entry_pin"]["path"]), "entry source origin differs")
        fence(request, launch_witness, captured)
        root = resource["cwd"]
        sys.path.insert(0, root)
        helper = checked_module("_legal_ir_live_registration_scope", request["resource_scope_pin"],
                                captured["resource_scope_pin"][0])
        driver = checked_module("_legal_ir_live_registration_driver", request["driver_pin"], captured["driver_pin"][0])
        fence(request, launch_witness, captured)
        scope = helper.ModelManagerRegistrationScope(request_path=request["resource_request_pin"]["path"],
            expected_request_sha256=request["resource_request_pin"]["sha256"])
        with scope:
            # The driver creates exports only after authenticating this original
            # live scope. No directory/file is created in the attempt earlier.
            result = driver.run_request(request["registration_request_pin"]["path"],
                request["registration_request_pin"]["sha256"], register=True, registration_scope=scope)
            fence(request, launch_witness, captured)
            sealed = scope.seal(result["path"])
            scope.finalize(artifacts_durable=True)
        terminal.update(complete=True, registration_result_pin=result, durability_pin=sealed)
    except BaseException as error:
        terminal["failure_type"] = type(error).__name__
    if scope is not None:
        terminal["resource_observation"] = scope.snapshot()
        # Private controller stdout only. This may contain native identifiers;
        # publication requires a separately reviewed redacted projection.
        if scope._owner is not None:
            terminal["private_native_closeout"] = scope._owner.to_dict()
    terminal["authority"] = {name: False for name in ("model_restored", "training_executed", "inference_executed",
        "teacher_qualified", "runtime_ready", "proof_authority", "gold_eligible")}
    print(wire(terminal).decode(), flush=True)
    return 0 if terminal["complete"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launch-request", required=True)
    parser.add_argument("--expected-launch-request-sha256", required=True)
    args = parser.parse_args()
    os.umask(0o077)
    raise SystemExit(run(args.launch_request, args.expected_launch_request_sha256))


if __name__ == "__main__":
    main()
