"""Inert lifecycle controls; no scheduler, ledger, database or product imports."""
import hashlib
from pathlib import Path
import sys
import types

import pytest


def helper():
    path = Path(__file__).with_name("registration_resource_scope.py")
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "704f6a37e8eaae4aec9064fa24123a48a41b162ac597d80d0ada1b087b74a8f5"
    name = "_registration_scope_inert_cleanup_controls"
    module = types.ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    try:
        exec(compile(raw, str(path), "exec"), module.__dict__)
    finally:
        sys.modules.pop(name, None)
    return module


def inert_scope(module, *, alive):
    events = []

    class Watchdog:
        def join(self, *, timeout):
            events.append(("join", timeout))

        def is_alive(self):
            return alive

    class Lease:
        def release(self):
            events.append("lease_release")

    class Owner:
        _lease = Lease()

        def _retain(self, reason):
            events.append(("retain", reason))

    scope = module.ModelManagerRegistrationScope.__new__(module.ModelManagerRegistrationScope)
    scope._stop = types.SimpleNamespace(set=lambda: events.append("stop"))
    scope._watchdog = Watchdog()
    scope._owner = Owner()
    scope._finished = False
    scope._fault = None
    scope._lock_fd = object()
    scope._group = lambda **kw: events.append(("group", kw))
    scope._unlock = lambda: events.append("unlock")
    return scope, events


def test_undrained_watchdog_preserves_original_error_and_all_resource_custody():
    module = helper()
    scope, events = inert_scope(module, alive=True)
    original = ValueError("authored original failure")
    assert scope.__exit__(ValueError, original, None) is False
    assert scope._fault == "metadata_watchdog_not_drained"
    assert events == ["stop", ("join", 5)]


def test_undrained_watchdog_refuses_clean_exit_without_concurrent_native_updates():
    module = helper()
    scope, events = inert_scope(module, alive=True)
    with pytest.raises(module.RegistrationResourceError, match="watchdog did not drain"):
        scope.__exit__(None, None, None)
    assert scope._fault == "metadata_watchdog_not_drained"
    assert events == ["stop", ("join", 5)]


def test_drained_watchdog_retains_failed_claim_then_releases_lease_and_writer_lock():
    module = helper()
    scope, events = inert_scope(module, alive=False)
    assert scope.__exit__(ValueError, ValueError("authored failure"), None) is False
    assert events == ["stop", ("join", 5), ("group", {"drained": True}),
                      ("retain", "metadata_registration_failed"), "lease_release", "unlock"]
    assert scope._fault is None
