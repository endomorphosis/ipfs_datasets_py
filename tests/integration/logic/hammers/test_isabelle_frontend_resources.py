"""Public capture rejects incomplete or mismatched native evidence."""
import hashlib
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.external_provers.isabelle_runtime import theory_command
from ipfs_datasets_py.logic.hammers.frontends import isabelle as module
from ipfs_datasets_py.logic.hammers.frontends.base import GoalCaptureError, FrontendUnavailableError
from tests.integration.logic.hammers.isabelle_execution_fixtures import unavailable_operation

SOURCE = 'theory ResourceGoal\nimports Main\nbegin\nlemma checked: "True"\nsorry\nend\n'
TRANSCRIPT = 'goal (1 subgoal):\n 1. True\n\n'


def completed_receipt(source):
    return SimpleNamespace(
        status="completed", reason_code="bounded_isabelle_operation_completed",
        runtime_unchanged=True, source_sha256=hashlib.sha256(source.encode()).hexdigest(),
        theory_name="ResourceGoal", native_runtime={"executable": "/fake/isabelle", "version": "Isabelle2025-2"},
        preparation=SimpleNamespace(command_available=True),
        observation=SimpleNamespace(
            command=tuple(theory_command("/fake/isabelle", "ResourceGoal", "{workspace}", capture=True)),
            returncode=0, stdout=TRANSCRIPT, stderr="", error="", cancelled=False, timed_out=False,
            unavailable=False, output_truncated=False, resource_exhausted=False,
            workspace_limit_exceeded=False, workspace_cleaned=True),
        to_dict=lambda: {"status": "completed", "grants_proof_authority": False},
    )


@pytest.mark.parametrize("field,value", [
    ("cancelled", True), ("timed_out", True), ("unavailable", True), ("output_truncated", True),
    ("resource_exhausted", True), ("workspace_limit_exceeded", True), ("workspace_cleaned", False),
    ("error", "native lifecycle incomplete"), ("returncode", 1), ("command", ("other",)),
])
def test_native_goal_text_does_not_override_failed_lifecycle(monkeypatch, field, value):
    def run(**kwargs):
        receipt = completed_receipt(kwargs["source"])
        setattr(receipt.observation, field, value)
        return receipt
    monkeypatch.setattr(module, "run_isabelle_operation", run)
    with pytest.raises(GoalCaptureError) as caught:
        module.IsabelleFrontend().snapshot_goal(SOURCE, theorem_id="checked")
    assert caught.value.execution["grants_proof_authority"] is False


@pytest.mark.parametrize("field,value", [
    ("status", "timed_out"), ("status", "cancelled"), ("status", "error"),
    ("runtime_unchanged", False), ("source_sha256", "0" * 64), ("theory_name", "OtherTheory"),
])
def test_valid_native_output_requires_current_matching_operation(monkeypatch, field, value):
    def run(**kwargs):
        receipt = completed_receipt(kwargs["source"])
        setattr(receipt, field, value)
        return receipt
    monkeypatch.setattr(module, "run_isabelle_operation", run)
    with pytest.raises(GoalCaptureError) as caught:
        module.IsabelleFrontend().snapshot_goal(SOURCE, theorem_id="checked")
    assert caught.value.execution["grants_proof_authority"] is False


def test_capture_uses_one_operation_with_callers_resource_context(monkeypatch):
    calls = []
    parent, cancellation = object(), object()
    def run(**kwargs):
        calls.append(kwargs)
        return completed_receipt(kwargs["source"])
    monkeypatch.setattr(module, "run_isabelle_operation", run)
    frontend = module.IsabelleFrontend(timeout=77, parent_lease=parent, cancellation=cancellation,
                                       memory_mb=1536, auto_install=True, install_root="/selected")
    snapshot = frontend.snapshot_goal(SOURCE, theorem_id="checked", timeout=11)
    assert len(calls) == 1
    call = calls[0]
    assert call["mode"] == "capture" and call["timeout_seconds"] == 11
    assert call["parent_lease"] is parent and call["cancellation"] is cancellation
    assert call["memory_mb"] == 1536 and call["auto_install"]
    assert call["install_root"] == "/selected" and call["executable"] is None
    assert call["source"] == SOURCE.replace("sorry", "print_state\nsorry")
    assert snapshot.goal_text == "True" and not snapshot.extra["execution"]["grants_proof_authority"]


def test_default_capture_keeps_installation_explicit(monkeypatch):
    calls = []
    def run(**kwargs):
        calls.append(kwargs)
        return unavailable_operation()
    monkeypatch.setattr(module, "run_isabelle_operation", run)
    with pytest.raises(FrontendUnavailableError) as caught:
        module.IsabelleFrontend().snapshot_goal(SOURCE, theorem_id="checked")
    assert len(calls) == 1 and not calls[0]["auto_install"]
    assert calls[0]["scheduler"] is None and calls[0]["parent_lease"] is None
    assert caught.value.capability.executables["isabelle"]["execution"]["status"] == "unavailable"


class SourceSubclass(str):
    pass


@pytest.mark.parametrize("source", [None, b"theory bytes", SourceSubclass(SOURCE),
    "x" * (1024**2), "\u20ac" * (400 * 1024), "\ud800", SOURCE + "\0"],
    ids=["none", "bytes", "str-subclass", "character-cap", "utf8-byte-cap", "invalid-unicode", "nul"])
def test_source_fence_precedes_instrumentation_and_native_work(monkeypatch, source):
    class ForbiddenScan:
        def search(self, source):
            pytest.fail("source reached marker scanning before validation")
    monkeypatch.setattr(module, "_SORRY_RE", ForbiddenScan())
    monkeypatch.setattr(module, "_instrument_isabelle_source", lambda *a: pytest.fail("instrumented rejected input"))
    monkeypatch.setattr(module, "run_isabelle_operation", lambda **kw: pytest.fail("admitted rejected input"))
    with pytest.raises(GoalCaptureError):
        module.IsabelleFrontend().snapshot_goal(source, theorem_id="checked")


def test_instrumentation_growth_uses_the_public_capture_error(monkeypatch):
    from ipfs_datasets_py.logic.backends.installers.isabelle_execution import MAX_SOURCE_BYTES
    source = SOURCE + " " * (MAX_SOURCE_BYTES - len(SOURCE))
    monkeypatch.setattr(module, "run_isabelle_operation", lambda **kw: pytest.fail("admitted oversized instrumented input"))
    with pytest.raises(GoalCaptureError):
        module.IsabelleFrontend().snapshot_goal(source, theorem_id="checked")
