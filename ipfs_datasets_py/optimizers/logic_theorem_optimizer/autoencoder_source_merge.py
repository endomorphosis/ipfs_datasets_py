"""Review and validate Git source integrations without editing the live checkout.

Only immutable commits are merged. Conflicts remain unresolved in the plan.
Application updates an internal integration ref after running an explicit source
validator in an isolated detached worktree. This is not model qualification,
Lean admission, publication to main, or promotion of a running source generation.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import tempfile
import time

from .autoencoder_source_lease import canonical_source_root, source_lease

SCHEMA = "autoencoder-source-merge/v1"
REF_PREFIX = "refs/autoencoder/integration/"
MAX_PLAN_BYTES = 2 * 1024 * 1024
MAX_VALIDATOR_LOG_BYTES = 8 * 1024 * 1024
DEFAULT_CHECKOUT_BYTES = 256 * 1024 * 1024


class SourceMergeError(RuntimeError):
    """The reviewed integration could not be verified or validated."""


def _environment():
    # Caller-selected indexes and repositories must never redirect an operation.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
    return env


def _git(root, *args, input=None, allowed=(0,), env=None):
    result = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c",
        "core.fsmonitor=false", "-c", "commit.gpgSign=false", "-C", str(root), *args],
        input=input, text=True, capture_output=True, timeout=60,
        env=env or _environment(), check=False)
    if result.returncode not in allowed:
        raise SourceMergeError((result.stderr or result.stdout or "Git command failed").strip())
    return result


def _commit(root, value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value):
        raise SourceMergeError("base and candidates must be full immutable commit IDs")
    observed = _git(root, "rev-parse", "--verify", value + "^{commit}").stdout.strip()
    if observed != value:
        raise SourceMergeError("object is not an exact commit")
    return observed


def _ref(root, name):
    if (not isinstance(name, str) or not name.startswith(REF_PREFIX)
            or not name[len(REF_PREFIX):] or name.endswith("/")
            or _git(root, "check-ref-format", name, allowed=(0, 1)).returncode):
        raise SourceMergeError("only refs/autoencoder/integration/<lane> may be updated")
    # Ref aliases could redirect an apparently internal update to main.
    if _git(root, "symbolic-ref", "-q", name, allowed=(0, 1)).returncode == 0:
        raise SourceMergeError("integration ref must not be symbolic")
    result = _git(root, "show-ref", "--verify", "--quiet", name, allowed=(0, 1))
    return _git(root, "rev-parse", "--verify", name).stdout.strip() if result.returncode == 0 else None


def _candidate_commit(root, tree, parents):
    env = _environment()
    env.update(GIT_AUTHOR_NAME="Autoencoder source integration", GIT_AUTHOR_EMAIL="integration@localhost",
        GIT_COMMITTER_NAME="Autoencoder source integration", GIT_COMMITTER_EMAIL="integration@localhost",
        GIT_AUTHOR_DATE="2000-01-01T00:00:00 +0000", GIT_COMMITTER_DATE="2000-01-01T00:00:00 +0000")
    args = ["commit-tree", tree]
    for parent in dict.fromkeys(parents):
        args.extend(["-p", parent])
    return _git(root, *args, input="Prepared source integration; no model qualification or admission.\n", env=env).stdout.strip()


def _merge(root, base, candidates):
    current, steps = base, []
    for candidate in candidates:
        result = _git(root, "merge-tree", "--write-tree", current, candidate, allowed=(0, 1))
        if len(result.stdout.encode()) + len(result.stderr.encode()) > MAX_PLAN_BYTES // 2:
            raise SourceMergeError("merge diagnostic exceeds plan bound")
        tree = result.stdout.splitlines()[0] if result.stdout else ""
        step = {"left_commit": current, "right_commit": candidate, "tree": tree,
                "conflicted": result.returncode != 0, "diagnostic": result.stdout,
                "stderr": result.stderr}
        steps.append(step)
        if result.returncode:
            return None, None, steps
        current = _candidate_commit(root, tree, [current, candidate])
    tree = _git(root, "rev-parse", current + "^{tree}").stdout.strip()
    return tree, _candidate_commit(root, tree, [base, *candidates]), steps


def prepare_source_merge(repo_root, *, base_commit, candidate_commits, integration_ref):
    """Create a reviewable plan; write Git objects but no refs or checkout files."""
    root = canonical_source_root(repo_root)
    base = _commit(root, base_commit)
    candidates = list(candidate_commits)
    if not 1 <= len(candidates) <= 16 or len(set(candidates)) != len(candidates):
        raise SourceMergeError("provide one to sixteen distinct candidate commits")
    candidates = [_commit(root, item) for item in candidates]
    expected = _ref(root, integration_ref)
    if expected is not None and expected != base:
        raise SourceMergeError("integration ref differs from requested immutable base")
    tree, commit, steps = _merge(root, base, candidates)
    return {"schema_version": SCHEMA, "repository": str(root), "base_commit": base,
            "candidate_commits": candidates, "integration_ref": integration_ref,
            "expected_ref_commit": expected, "merged_tree": tree, "integration_commit": commit,
            "status": "conflicted" if tree is None else "prepared", "steps": steps,
            "admitted": False, "model_qualified": False, "main_published": False}


def write_merge_plan(path, plan):
    """Exclusively create the exact review artifact and return its byte digest."""
    raw = (json.dumps(plan, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    if len(raw) > MAX_PLAN_BYTES:
        raise SourceMergeError("plan exceeds byte bound")
    with open(path, "xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(raw).hexdigest()


def _read_plan(path, expected_sha256):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_PLAN_BYTES:
            raise SourceMergeError("review plan must be a bounded unaliased regular file")
        raw = stream.read(MAX_PLAN_BYTES + 1)
    if len(raw) > MAX_PLAN_BYTES or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise SourceMergeError("review plan byte digest changed")
    plan = json.loads(raw)
    if not isinstance(plan, dict) or plan.get("schema_version") != SCHEMA or plan.get("status") != "prepared":
        raise SourceMergeError("only a nonconflicting prepared source plan can be applied")
    return plan


def _validate(root, plan, argv, *, timeout_seconds, max_checkout_bytes, directory,
              resource_reservation=None, resource_attempt_directory=None):
    entries = _git(root, "ls-tree", "-r", "-l", "-z", plan["merged_tree"]).stdout.split("\0")
    checkout_bytes, file_count = 0, 0
    for entry in entries:
        if not entry:
            continue
        metadata = entry.split("\t", 1)[0].split()
        if metadata[1] == "blob":
            checkout_bytes += int(metadata[3])
            file_count += 1
    if checkout_bytes > max_checkout_bytes or file_count > 100000:
        raise SourceMergeError("validation checkout exceeds explicit byte or file bound")
    worktree = directory / "checkout"
    log = directory / "validator.log"
    _git(root, "worktree", "add", "--detach", str(worktree), plan["integration_commit"])
    started = time.monotonic()
    reason = None
    def check_external_usage():
        if resource_reservation is not None:
            from .autoencoder_daemon_resources import _inventory
            observed = _inventory([directory], strict=False)
            if (observed["apparent_bytes"] > max_checkout_bytes + MAX_VALIDATOR_LOG_BYTES + 8 * 1024 * 1024
                    or observed["special_file_count"]):
                raise SourceMergeError("external validation checkout exceeds its byte bound or contains special files")
    try:
        check_external_usage()
        if resource_reservation is not None:
            resource_reservation.check_usage(resource_attempt_directory)
        env = _environment()
        env.pop("PYTHONHOME", None)
        env.pop("PYTHONINSPECT", None)
        env.update(PYTHONPATH=str(worktree), PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1",
                   AUTOENCODER_VALIDATION_SOURCE_ROOT=str(worktree),
                   AUTOENCODER_VALIDATION_GIT_TREE=plan["merged_tree"])
        # Use explicit cwd-relative commands. Existing native canonical-tree guards
        # remain authoritative; this command is source validation, not training.
        with open(log, "wb") as output:
            process = subprocess.Popen(argv, cwd=worktree, env=env, stdout=output,
                stderr=subprocess.STDOUT, start_new_session=True)
            try:
                if resource_reservation is not None:
                    resource_reservation.check_usage(resource_attempt_directory, child_pid=process.pid)
                next_resource_check = time.monotonic() + 2
                while process.poll() is None:
                    if resource_reservation is not None and time.monotonic() >= next_resource_check:
                        check_external_usage()
                        resource_reservation.check_usage(resource_attempt_directory, child_pid=process.pid)
                        next_resource_check = time.monotonic() + 2
                    if time.monotonic() - started > timeout_seconds:
                        reason = "validator timeout"
                        break
                    if output.tell() > MAX_VALIDATOR_LOG_BYTES:
                        reason = "validator log exceeds byte bound"
                        break
                    time.sleep(0.02)
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                        reason = reason or "validator left running children"
                    except ProcessLookupError:
                        pass
                process.wait()
            output.flush()
            os.fsync(output.fileno())
        with log.open("rb") as stream:
            raw = stream.read(MAX_VALIDATOR_LOG_BYTES)
        receipt = {"argv": argv, "returncode": process.returncode, "elapsed_seconds": time.monotonic() - started,
                   "checkout_bytes": checkout_bytes, "checkout_files": file_count,
                   "log": raw.decode(errors="replace"), "log_sha256": hashlib.sha256(raw).hexdigest(),
                   "merged_tree": plan["merged_tree"], "integration_commit": plan["integration_commit"],
                   "scope": "operator-specified source integration checks; not native training or qualification",
                   "python_import_policy": "PYTHONPATH contains only the isolated worktree; PYTHONHOME cleared; user site disabled. Validators must assert imported source origins, including ignored overlays.",
                   "source_root": str(worktree)}
        if reason or log.stat().st_size > MAX_VALIDATOR_LOG_BYTES or process.returncode:
            receipt["failure"] = reason or "validator failed"
            return receipt
        check_external_usage()
        observed_tree = _git(worktree, "write-tree").stdout.strip()
        changed = _git(worktree, "diff", "--quiet", "HEAD", "--", allowed=(0, 1)).returncode
        observed_head = _git(worktree, "rev-parse", "HEAD").stdout.strip()
        untracked = _git(worktree, "ls-files", "--others", "--exclude-standard", "-z").stdout
        if observed_tree != plan["merged_tree"] or changed or observed_head != plan["integration_commit"]:
            receipt["failure"] = "validator changed the tracked source tree or checkout commit"
        elif untracked:
            receipt["failure"] = "validator left untracked files outside ignored build outputs"
            receipt["untracked_files"] = untracked.split("\0")[:100]
        receipt["ignored_build_outputs_permitted"] = True
        return receipt
    finally:
        _git(root, "worktree", "remove", "--force", str(worktree))


def apply_source_merge(repo_root, *, plan_path, expected_plan_sha256, validator_argv,
                       validation_timeout_seconds=300.0, lease_timeout_seconds=300.0,
                       max_checkout_bytes=DEFAULT_CHECKOUT_BYTES, scratch_directory=None,
                       resource_reservation=None, resource_attempt_directory=None):
    """Validate then CAS-update only the internal ref under an exclusive lease.

    The explicit validator is trusted operator code, executed without a shell.
    Its success records only the checks it actually performs. Every invocation
    validates afresh; externally supplied success receipts are never accepted.
    """
    if (not isinstance(validator_argv, (tuple, list)) or not validator_argv
            or any(not isinstance(item, str) or not item or "\0" in item for item in validator_argv)):
        raise SourceMergeError("an explicit nonempty validator argv is required")
    if (type(validation_timeout_seconds) not in (int, float)
            or not math.isfinite(validation_timeout_seconds) or not 0 < validation_timeout_seconds <= 3600
            or type(max_checkout_bytes) is not int or not 0 < max_checkout_bytes <= 2 * 1024**3):
        raise SourceMergeError("invalid bounded source validation budget")
    if (resource_reservation is None) != (resource_attempt_directory is None):
        raise SourceMergeError("resource owner and attempt directory must be supplied together")
    root = canonical_source_root(repo_root)
    plan = _read_plan(plan_path, expected_plan_sha256)
    if plan.get("repository") != str(root):
        raise SourceMergeError("review plan names a different repository")
    with source_lease(root, mode="write", timeout_seconds=lease_timeout_seconds) as lease:
        current = _ref(root, plan["integration_ref"])
        if current != plan["expected_ref_commit"]:
            raise SourceMergeError("stale integration ref; prepare and review a new merge")
        recomputed = prepare_source_merge(root, base_commit=plan["base_commit"],
            candidate_commits=plan["candidate_commits"], integration_ref=plan["integration_ref"])
        if recomputed != plan:
            raise SourceMergeError("review plan does not reproduce from its immutable commits")
        with tempfile.TemporaryDirectory(prefix="autoencoder-source-validation-", dir=scratch_directory) as temporary:
            validation = _validate(root, plan, list(validator_argv),
                timeout_seconds=float(validation_timeout_seconds), max_checkout_bytes=max_checkout_bytes,
                directory=Path(temporary), resource_reservation=resource_reservation,
                resource_attempt_directory=resource_attempt_directory)
        receipt = {"schema_version": SCHEMA, "plan_sha256": expected_plan_sha256,
            "integration_ref": plan["integration_ref"], "integration_commit": plan["integration_commit"],
            "merged_tree": plan["merged_tree"], "validation": validation, "lease": lease.to_dict(),
            "applied": False, "admitted": False, "model_qualified": False, "main_published": False}
        if "failure" in validation:
            return receipt
        if resource_reservation is not None:
            resource_reservation.check_usage(resource_attempt_directory)
        # --no-deref plus the preflight symbolic-ref check prevents alias writes.
        if _ref(root, plan["integration_ref"]) != current:
            receipt["failure"] = "stale integration ref after source validation"
            return receipt
        expected = current or "0" * len(plan["base_commit"])
        try:
            _git(root, "update-ref", "--no-deref", plan["integration_ref"], plan["integration_commit"], expected)
        except SourceMergeError as exc:
            receipt["failure"] = "integration ref compare-and-swap failed: " + str(exc)
            return receipt
        receipt["applied"] = True
        return receipt
