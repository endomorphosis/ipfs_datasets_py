"""Integration contract for Lean and Rocq/Coq kernel-checking backends.

Covers LFV-G049 / LFV-022 acceptance:

* kernel receipts bind theorem, imports, generated proof, toolchain, source
  tree, and translation;
* Lean ``sorry`` / unsafe axioms and Rocq/Coq ``Admitted`` reject or
  explicitly downgrade authority;
* native and WASM/browser capability planes are separate with explicit WASM
  absence;
* failure diagnostics are inert and bounded;
* unavailable kernels never pass.
"""

from __future__ import annotations

import json
import copy
import os
import re
from pathlib import Path

import pytest
from ipfs_datasets_py.logic.backends.kernel.lean import (
    LEAN_KERNEL_BACKEND_VERSION,
    LeanAuthorityDisposition,
    LeanKernelBackend,
    LeanKernelReceipt,
    LeanKernelError,
    evaluate_lean_kernel_output,
    instrument_lean_source_for_axioms,
    scan_lean_incomplete_or_unsafe,
)
from ipfs_datasets_py.logic.backends.kernel.rocq import (
    ROCQ_KERNEL_BACKEND_VERSION,
    RocqAuthorityDisposition,
    RocqKernelBackend,
)
from ipfs_datasets_py.logic.backends.kernel.wasm import (
    CapabilityAvailability,
    CapabilityPlane,
    DualPlaneCapability,
    KernelCapabilityState,
    WasmCapabilityProbe,
    bound_diagnostics,
    sanitize_diagnostic,
)
from ipfs_datasets_py.logic.backends.process import (
    BoundedToolRunner,
    RawProcessResult,
    ToolRunResult,
    ToolRuntime,
    ToolRunRequest,
    ToolRunLimits,
)
from ipfs_datasets_py.logic.backends.results import (
    CandidateResult,
    ResultAuthority,
    ResultStatus,
    TheoremResult,
)
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap, stable_digest
from ipfs_datasets_py.logic.ir_core.protocols import (
    BackendRequest,
    ExecutionBounds,
    QueryKind,
)

LEAN_OK = """\
import Init.Prelude

theorem and_comm (p q : Prop) : p ∧ q → q ∧ p := by
  intro h
  exact And.intro h.right h.left
"""

LEAN_SORRY = """\
theorem incomplete (n : Nat) : n = n := by
  sorry
"""

LEAN_UNSAFE = """\
unsafe def bad : Nat := 0
theorem still_there : True := by
  trivial
"""

ROCQ_OK = """\
Require Import Lia.

Theorem add_comm : forall n m : nat, n + m = m + n.
Proof.
  intros n m.
  lia.
Qed.
"""

ROCQ_ADMITTED = """\
Theorem incomplete : forall n : nat, n = n.
Proof.
  intros n.
  admit.
Admitted.
"""


def _request(
    *,
    family: str,
    encoding: str,
    source: str,
    backend_id: str = "",
    translation: dict | None = None,
    bounds: ExecutionBounds | None = None,
    expected_declaration: str | None = None,
    expected_proposition: str | None = None,
) -> BackendRequest:
    payload: dict = {"encoding": encoding, "source": source}
    if translation is not None:
        payload["translation"] = translation
    if expected_declaration is not None:
        payload["expected_declaration"] = expected_declaration
    if expected_proposition is not None:
        payload["expected_proposition"] = expected_proposition
    return BackendRequest(
        request_id="request:kernel:test",
        claim_id="claim:kernel:test",
        declaration_id="declaration:kernel:test",
        claim_digest="1" * 64,
        obligation_id="obligation:kernel:test",
        obligation_digest="2" * 64,
        assumption_ids=("assumption:reviewed",),
        logic_family=family,
        query_kind=QueryKind.THEOREM_PROOF,
        bounds=bounds or ExecutionBounds(timeout_ms=250, max_steps=20),
        payload=FrozenMap(payload),
        requested_backend_id=backend_id,
    )


def _translation(target_family: str) -> dict:
    return {
        "translation_id": "translation:kernel:test",
        "translation_digest": "3" * 64,
        "source_family": "software_verification",
        "target_family": target_family,
        "fidelity": "exact",
    }


def _fictional_native_identity(*, executable="/fictional/lean", version="test"):
    from ipfs_datasets_py.logic.backends.kernel import lean
    stats=lean.FrozenMap(dict(device=1,inode=1,size=1,mtime_ns=1,ctime_ns=1))
    return lean.LeanNativeIdentity(resolved_executable=executable,executable_sha256="d"*64,executable_bytes=1,
        executable_stat_before=stats,executable_stat_after=stats,actual_version=version,
        version_stdout="Lean (version "+version+")",version_stderr="",version_command=(executable,"--version"),
        version_returncode=0,observation_kind="trusted_fictional_identity_fixture")


def _process_runner(
    stdout: str,
    *,
    returncode: int | None = 0,
    timed_out: bool = False,
    unavailable: bool = False,
    output_truncated: bool = False,
    expected_suffix: str = "",
    adapt_guard_reports: bool = True,
) -> tuple[BoundedToolRunner, list[object]]:
    invocations: list[object] = []

    def execute(invocation, _cancellation):
        invocations.append(invocation)
        if expected_suffix:
            # Ensure instrumented source was written into the private workspace.
            written = list(invocation.input_files.values()) if hasattr(
                invocation, "input_files"
            ) else []
            if not written and hasattr(invocation, "cwd"):
                candidates = list(invocation.cwd.glob("*"))
                assert candidates, "expected instrumented source in workspace"
                content = candidates[0].read_text(encoding="utf-8")
                assert expected_suffix in content
        rendered = stdout
        # Explicitly mocked compiler provenance, derived from the actual prepared
        # input. These unit fixtures establish no native Lean execution result.
        lean_path = invocation.cwd / "Main.lean"
        if lean_path.is_file():
            content = lean_path.read_text(encoding="utf-8")
            line = content[:content.rfind("#print axioms")].count("\n") + 1
            rows = []
            for raw in stdout.splitlines():
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    rows.append(raw)
                    continue
                if isinstance(message, dict):
                    # Authored fixtures follow the generated guard name. They
                    # are mocked compiler messages and confer no native evidence.
                    audit_name=re.search(r"#print axioms _root_\.([A-Za-z0-9_'.]+)\s*$",content)
                    goal=re.search(r"theorem (_ipfs_expected_obligation_[a-f0-9]+) : .* := _root_\.([A-Za-z0-9_'.]+)",content)
                    data=message.get("data","")
                    if adapt_guard_reports and audit_name and goal and isinstance(data,str) and data.startswith("'"+goal.group(2)+"' "):
                        message["data"]="'"+audit_name.group(1)+"' "+data[len(goal.group(2))+3:]
                    message.setdefault("fileName", invocation.argv[-1])
                    message.setdefault("pos", {"line": line, "column": 0})
                rows.append(json.dumps(message))
            rendered = "\n".join(rows) + ("\n" if rows else "")
        return RawProcessResult(
            returncode=returncode,
            stdout=rendered,
            elapsed_seconds=0.011,
            timed_out=timed_out,
            output_truncated=output_truncated,
            process_tree_terminated=timed_out,
            error="executable not found" if unavailable else "",
        )

    return BoundedToolRunner(executor=execute), invocations


def _available_native(kernel_id: str, executable: str) -> KernelCapabilityState:
    return KernelCapabilityState.available_native(
        kernel_id=kernel_id,
        executable=executable,
        version="test",
    )


def test_wasm_absence_is_explicit_and_separate_from_native():
    probe = WasmCapabilityProbe()
    wasm = probe.probe(kernel_id="lean", module_id="lean4-wasm")
    assert wasm.plane is CapabilityPlane.WASM
    assert wasm.availability is CapabilityAvailability.UNAVAILABLE
    assert wasm.available is False
    assert wasm.metadata["explicit_absence"] is True
    assert "explicitly absent" in wasm.reason

    dual = DualPlaneCapability(
        kernel_id="lean",
        native=_available_native("lean", "lean"),
        wasm=wasm,
    )
    assert dual.native_available is True
    assert dual.wasm_available is False
    assert dual.native.plane is CapabilityPlane.NATIVE
    assert dual.wasm.plane is CapabilityPlane.WASM
    assert dual.to_dict()["native_available"] is True
    assert dual.to_dict()["wasm_available"] is False


def test_wasm_probe_supports_injected_module_without_implying_native():
    probe = WasmCapabilityProbe(
        module_locator=lambda module_id: f"/modules/{module_id}.wasm"
    )
    wasm = probe.probe(kernel_id="rocq", module_id="rocq-wasm")
    assert wasm.available is True
    assert wasm.module_id == "rocq-wasm"
    assert wasm.executable.endswith("rocq-wasm.wasm")

    backend = RocqKernelBackend(
        runner=BoundedToolRunner(executor=lambda *_: RawProcessResult(returncode=1)),
        wasm_probe=probe,
        native_probe=lambda: KernelCapabilityState.unavailable(
            plane=CapabilityPlane.NATIVE,
            kernel_id="rocq",
            reason="native coqtop not installed in this fixture",
            executable="coqtop",
        ),
    )
    capability = backend.probe_capabilities()
    assert capability.native_available is False
    assert capability.wasm_available is True
    assert backend.is_available() is False


def test_diagnostics_are_inert_and_bounded():
    noisy = "secret\x00token\n" + ("A" * 2000) + "\n\n\nline"
    cleaned = sanitize_diagnostic(noisy, max_chars=64)
    assert "\x00" not in cleaned
    assert len(cleaned) <= 64
    assert cleaned.endswith("...")
    bounded = bound_diagnostics([noisy, noisy, "ok", ""], max_items=2, max_chars=32)
    assert len(bounded) == 2
    assert all(len(item) <= 32 for item in bounded)


def test_lean_verified_proof_binds_full_kernel_receipt():
    axiom_message = {
        "severity": "info",
        "data": "'and_comm' does not depend on any axioms",
    }
    runner, invocations = _process_runner(
        json.dumps(axiom_message) + "\n",
        expected_suffix="set_option autoImplicit false in",
    )
    backend = LeanKernelBackend(native_identity_probe=lambda:_fictional_native_identity(version="4.31.0"),
        runner=runner,
        backend_version="4.31.0",
        native_probe=lambda: _available_native("lean", "lean"),
        wasm_probe=WasmCapabilityProbe(),
    )
    request = _request(
        family="lean4",
        encoding="lean4",
        source=LEAN_OK,
        backend_id="lean",
        translation=_translation("lean4"),
        expected_declaration="and_comm",
        expected_proposition="∀ (p q : Prop), p ∧ q → q ∧ p",
    )

    outcome = backend.run(request)

    assert outcome.interface_version == LEAN_KERNEL_BACKEND_VERSION
    assert isinstance(outcome.result, TheoremResult)
    assert outcome.result.status is ResultStatus.PROVED
    assert outcome.result.authority is ResultAuthority.THEOREM
    assert outcome.receipt.accepted is True
    assert outcome.receipt.theorem_name == "and_comm"
    assert outcome.receipt.imports == ("Init.Prelude",)
    assert outcome.receipt.generated_proof
    assert outcome.receipt.generated_proof_digest == stable_digest(
        {"content": outcome.receipt.generated_proof}
    )
    assert outcome.receipt.toolchain.plane is CapabilityPlane.NATIVE
    assert outcome.receipt.toolchain.executable == "/fictional/lean"
    assert outcome.receipt.source_tree.primary_path == "Main.lean"
    assert "Main.lean" in outcome.receipt.source_tree.files
    assert outcome.receipt.translation is not None
    assert outcome.receipt.translation.translation_id == "translation:kernel:test"
    assert outcome.receipt.axiom_report is not None
    assert outcome.receipt.axiom_report.contains_sorry_ax is False
    assert outcome.result.witness["receipt_id"] == outcome.receipt.receipt_id
    assert outcome.capability.native_available is True
    assert outcome.capability.wasm_available is False
    assert outcome.capability.wasm.metadata["explicit_absence"] is True
    assert invocations, "lean runner should have been invoked"


def test_lean_sorry_is_rejected_and_never_proved():
    backend = LeanKernelBackend(native_identity_probe=_fictional_native_identity,
        runner=BoundedToolRunner(
            executor=lambda *_: RawProcessResult(
                returncode=0,
                stdout=json.dumps(
                    {
                        "severity": "info",
                        "data": "'incomplete' depends on axioms: sorryAx",
                    }
                )
                + "\n",
            )
        ),
        native_probe=lambda: _available_native("lean", "lean"),
    )
    outcome = backend.run(
        _request(family="lean4", encoding="lean4", source=LEAN_SORRY)
    )

    assert outcome.result.status is ResultStatus.MALFORMED
    assert outcome.receipt.accepted is False
    assert "lean_source_contains_sorry_or_admit" in outcome.receipt.diagnostics
    assert outcome.result.status is not ResultStatus.PROVED


def test_lean_sorry_can_explicitly_downgrade_authority():
    backend = LeanKernelBackend(native_identity_probe=_fictional_native_identity,
        incomplete_disposition=LeanAuthorityDisposition.DOWNGRADE,
        native_probe=lambda: _available_native("lean", "lean"),
    )
    outcome = backend.run(
        _request(family="lean4", encoding="lean4", source=LEAN_SORRY)
    )
    assert isinstance(outcome.result, CandidateResult)
    assert outcome.result.authority is ResultAuthority.CANDIDATE
    assert outcome.result.status is ResultStatus.CANDIDATE
    assert outcome.result.witness["candidate_kind"] == "incomplete_or_unsafe_lean_proof"
    assert outcome.receipt.authority_disposition is LeanAuthorityDisposition.DOWNGRADE
    assert outcome.receipt.accepted is False


def test_lean_unsafe_axiom_is_rejected():
    backend = LeanKernelBackend(native_identity_probe=_fictional_native_identity,
        native_probe=lambda: _available_native("lean", "lean"),
    )
    outcome = backend.run(
        _request(family="lean4", encoding="lean4", source=LEAN_UNSAFE)
    )
    assert outcome.result.status is ResultStatus.MALFORMED
    assert "lean_source_contains_unsafe_or_unreviewed_axiom" in outcome.receipt.diagnostics
    assert outcome.receipt.accepted is False


def test_unavailable_lean_kernel_never_passes():
    backend = LeanKernelBackend(native_identity_probe=_fictional_native_identity,
        native_probe=lambda: KernelCapabilityState.unavailable(
            plane=CapabilityPlane.NATIVE,
            kernel_id="lean",
            reason="lean executable not found on PATH",
            executable="lean",
        ),
        wasm_probe=WasmCapabilityProbe(),
    )
    outcome = backend.run(
        _request(family="lean4", encoding="lean4", source=LEAN_OK)
    )
    assert outcome.result.status is ResultStatus.UNAVAILABLE
    assert outcome.receipt.accepted is False
    assert outcome.result.authority is ResultAuthority.THEOREM
    assert outcome.result.status is not ResultStatus.PROVED
    assert "not found" in outcome.result.reason


def test_lean_wasm_plane_is_probe_only_and_not_confused_with_native_success():
    probe = WasmCapabilityProbe(
        module_locator=lambda module_id: f"memory://{module_id}"
    )
    backend = LeanKernelBackend(native_identity_probe=_fictional_native_identity,
        native_probe=lambda: _available_native("lean", "lean"),
        wasm_probe=probe,
    )
    capability = backend.probe_capabilities()
    assert capability.native_available is True
    assert capability.wasm_available is True
    assert capability.browser is not None
    assert capability.browser.available is True

    outcome = backend.run(
        _request(family="lean4", encoding="lean4", source=LEAN_OK),
        plane=CapabilityPlane.WASM,
    )
    assert outcome.result.status is ResultStatus.UNSUPPORTED
    assert outcome.receipt.plane is CapabilityPlane.WASM
    assert outcome.receipt.accepted is False
    assert outcome.receipt.toolchain.module_id == "lean4-wasm"


def test_rocq_verified_proof_binds_full_kernel_receipt():
    runner, invocations = _process_runner(
        f"Closed under the global context\n",
        expected_suffix="Print Assumptions add_comm",
    )
    backend = RocqKernelBackend(
        runner=runner,
        backend_version="9.1.1",
        native_probe=lambda: _available_native("rocq", "coqtop"),
        wasm_probe=WasmCapabilityProbe(),
    )
    request = _request(
        family="rocq",
        encoding="rocq",
        source=ROCQ_OK,
        backend_id="rocq",
        translation=_translation("rocq"),
    )

    outcome = backend.run(request)

    assert outcome.interface_version == ROCQ_KERNEL_BACKEND_VERSION
    assert isinstance(outcome.result, TheoremResult)
    assert outcome.result.status is ResultStatus.PROVED
    assert outcome.receipt.accepted is True
    assert outcome.receipt.theorem_name == "add_comm"
    assert any("Lia" in item for item in outcome.receipt.imports)
    assert outcome.receipt.generated_proof
    assert outcome.receipt.toolchain.executable == "coqtop"
    assert outcome.receipt.source_tree.primary_path == "Main.v"
    assert outcome.receipt.translation is not None
    assert outcome.receipt.assumption_report is not None
    assert outcome.receipt.assumption_report.closed_under_global_context is True
    assert outcome.capability.wasm_available is False
    assert outcome.capability.wasm.metadata["explicit_absence"] is True
    assert invocations


def test_rocq_admitted_is_rejected_and_never_proved():
    backend = RocqKernelBackend(
        native_probe=lambda: _available_native("rocq", "coqtop"),
    )
    outcome = backend.run(
        _request(family="rocq", encoding="coq", source=ROCQ_ADMITTED)
    )
    assert outcome.result.status is ResultStatus.MALFORMED
    assert "rocq_source_contains_admit_or_admitted" in outcome.receipt.diagnostics
    assert outcome.receipt.accepted is False
    assert outcome.result.status is not ResultStatus.PROVED


def test_rocq_admitted_can_explicitly_downgrade_authority():
    backend = RocqKernelBackend(
        incomplete_disposition=RocqAuthorityDisposition.DOWNGRADE,
        native_probe=lambda: _available_native("rocq", "coqtop"),
    )
    outcome = backend.run(
        _request(family="rocq", encoding="coq", source=ROCQ_ADMITTED)
    )
    assert isinstance(outcome.result, CandidateResult)
    assert outcome.result.authority is ResultAuthority.CANDIDATE
    assert outcome.result.witness["candidate_kind"] == "incomplete_or_admitted_rocq_proof"
    assert outcome.receipt.authority_disposition is RocqAuthorityDisposition.DOWNGRADE


def test_unavailable_rocq_kernel_never_passes():
    backend = RocqKernelBackend(
        native_probe=lambda: KernelCapabilityState.unavailable(
            plane=CapabilityPlane.NATIVE,
            kernel_id="rocq",
            reason="coqtop executable not found on PATH",
            executable="coqtop",
        )
    )
    outcome = backend.run(
        _request(family="rocq", encoding="rocq", source=ROCQ_OK)
    )
    assert outcome.result.status is ResultStatus.UNAVAILABLE
    assert outcome.receipt.accepted is False
    assert outcome.result.status is not ResultStatus.PROVED


def test_lean_hidden_sorry_ax_from_kernel_output_is_rejected():
    """Exit code 0 alone is insufficient when sorryAx appears in axiom report."""

    runner, _ = _process_runner(
        json.dumps(
            {
                "severity": "info",
                "data": "'and_comm' depends on axioms: [sorryAx]",
            }
        )
        + "\n",
        returncode=0,
    )
    backend = LeanKernelBackend(native_identity_probe=_fictional_native_identity,
        runner=runner,
        native_probe=lambda: _available_native("lean", "lean"),
    )
    outcome = backend.run(
        _request(family="lean4", encoding="lean4", source=LEAN_OK)
    )
    assert outcome.receipt.accepted is False
    assert outcome.result.status in {
        ResultStatus.MALFORMED,
        ResultStatus.ERROR,
        ResultStatus.CANDIDATE,
    }
    assert outcome.result.status is not ResultStatus.PROVED
    assert any("sorryAx" in item for item in outcome.receipt.diagnostics)


def test_rocq_exit_zero_without_closed_context_is_rejected():
    runner, _ = _process_runner(
        "Axioms:\nadmit : False\n",
        returncode=0,
    )
    backend = RocqKernelBackend(
        runner=runner,
        native_probe=lambda: _available_native("rocq", "coqtop"),
    )
    outcome = backend.run(
        _request(family="rocq", encoding="rocq", source=ROCQ_OK)
    )
    assert outcome.receipt.accepted is False
    assert outcome.result.status is not ResultStatus.PROVED
    assert any(
        "Closed under the global context" in item for item in outcome.receipt.diagnostics
    )


def test_interface_versions_are_stable():
    assert LEAN_KERNEL_BACKEND_VERSION == "LeanKernelBackend@1"
    assert ROCQ_KERNEL_BACKEND_VERSION == "RocqKernelBackend@1"
    assert LeanKernelBackend(native_identity_probe=_fictional_native_identity, ).interface_version == LEAN_KERNEL_BACKEND_VERSION
    assert RocqKernelBackend().interface_version == ROCQ_KERNEL_BACKEND_VERSION


# Security regression controls use deliberately mocked compiler output. Actual
# native checks are separately opt-in and emit their own execution record below.
def _lean_output(stdout, *, error="", stderr=""):
    return ToolRunResult(interface_version="mocked-compiler-output-only/v1", runtime=ToolRuntime.NATIVE,
        command=("fixture-not-an-executed-compiler",), returncode=0, stdout=stdout, stderr=stderr,
        elapsed_seconds=0, output_files={}, error=error)


def _axiom_message(data, **fields):
    return json.dumps({"severity":"information", "data":data, **fields}) + "\n"


@pytest.mark.parametrize("stdout", [
    _axiom_message("'other' does not depend on any axioms"),
    _axiom_message("'wanted' depends on axioms: [unapproved_axiom]"),
    _axiom_message("'wanted' does not depend on any axioms") * 2,
    _axiom_message("'wanted' does not depend on any axioms") + _axiom_message("'wanted' depends on axioms: [sorryAx]"),
    _axiom_message("prefix 'wanted' does not depend on any axioms"),
    _axiom_message("'wanted' does not depend on any axioms suffix"),
    _axiom_message("'wanted' does not depend on any axioms", severity="warning"),
    _axiom_message("'wanted' depends on axioms: [Classical.choice, Classical.choice]"),
    _axiom_message("'wanted' depends on axioms: sorryAx"),
    "does not depend on any axioms\n",
    json.dumps([{"severity":"information","data":"'wanted' does not depend on any axioms"}]),
    '{"severity":"error","severity":"information","data":"\'wanted\' does not depend on any axioms"}',
])
def test_lean_rejects_unbound_ambiguous_or_unapproved_compiler_reports(stdout):
    accepted, _, _ = evaluate_lean_kernel_output(_lean_output(stdout), declaration="wanted")
    assert accepted is False


def test_lean_approved_policy_is_explicit_and_sorry_cannot_be_approved():
    stdout = _axiom_message("'wanted' depends on axioms: [Classical.choice]")
    assert evaluate_lean_kernel_output(_lean_output(stdout), declaration="wanted")[0] is False
    accepted, report, _ = evaluate_lean_kernel_output(_lean_output(stdout), declaration="wanted",
                                                    approved_axioms=("Classical.choice",))
    assert accepted and report.axioms == ("Classical.choice",)
    with pytest.raises(LeanKernelError):
        LeanKernelBackend(native_identity_probe=_fictional_native_identity, approved_axioms=("sorryAx",))


def test_lean_error_or_stderr_report_cannot_be_rescued_by_clean_stdout():
    stdout = _axiom_message("'wanted' does not depend on any axioms")
    assert evaluate_lean_kernel_output(_lean_output(stdout,error="fixture failure"),declaration="wanted")[0] is False
    assert evaluate_lean_kernel_output(_lean_output(stdout,stderr="'wanted' depends on axioms: [sorryAx]"),declaration="wanted")[0] is False


@pytest.mark.parametrize("fields", [
    {"fileName":"/other/Main.lean","pos":{"line":7,"column":0}},
    {"fileName":"/expected/Main.lean","pos":{"line":6,"column":0}},
    {"fileName":"/expected/Main.lean","pos":{"line":7,"column":2}},
    {"fileName":"/expected/Main.lean","pos":{"line":True,"column":0}},
    {},
])
def test_lean_requires_compiler_report_at_the_instrumented_source_position(fields):
    stdout = _axiom_message("'wanted' does not depend on any axioms",**fields)
    accepted, _, _ = evaluate_lean_kernel_output(_lean_output(stdout),declaration="wanted",
        expected_source_path="/expected/Main.lean",expected_source_line=7)
    assert accepted is False


def _bound_lean_outcome(*, source="theorem wanted : True := by trivial\n", name="wanted", proposition="True",
                        stdout=None, approved_axioms=()):
    if stdout is None:
        stdout = _axiom_message("'"+name+"' does not depend on any axioms")
    runner, calls = _process_runner(stdout)
    backend = LeanKernelBackend(native_identity_probe=_fictional_native_identity, runner=runner,approved_axioms=approved_axioms,
        native_probe=lambda:_available_native("lean","fixture-not-an-executed-compiler"))
    request = _request(family="lean4",encoding="lean4",source=source,
                       expected_declaration=name,expected_proposition=proposition)
    return backend.run(request), calls, request


def test_lean_v2_receipt_binds_expected_goal_policy_and_round_trips_strictly():
    outcome, calls, request = _bound_lean_outcome()
    assert calls and outcome.result.status is ResultStatus.PROVED
    receipt = outcome.receipt
    assert receipt.schema_version == "lean-kernel-receipt/v3"
    assert receipt.expected_proposition == "True" and receipt.expected_proposition_checked is True
    assert receipt.axiom_report.declaration == receipt.expected_obligation_declaration
    assert receipt.axiom_report.source_line > 0 and receipt.axiom_report.source_column == 0
    assert receipt.approved_axioms == ()
    assert LeanKernelReceipt.from_dict(receipt.to_dict()).to_dict() == receipt.to_dict()


@pytest.mark.parametrize("mutation", ["missing_report","wrong_report_name","unapproved_dependency","missing_typecheck",
    "wrong_proposition_digest","missing_compiled_source","wrong_source","wrong_proof","wrong_toolchain_policy",
    "missing_report_position","unknown_field","legacy_schema","missing_source","wrong_submitted_source",
    "wrong_compiled_recipe","wrong_selected_declaration","wrong_report_line","empty_report_text",
    "wrong_declaration_report_text","hidden_sorry_report_text","hidden_dependency_report_text"])
def test_lean_v2_receipt_rejects_internal_evidence_mutations_even_with_recomputed_id(mutation):
    outcome, _, _ = _bound_lean_outcome()
    value = copy.deepcopy(outcome.receipt.to_dict())
    if mutation == "missing_report": value["axiom_report"] = None
    elif mutation == "wrong_report_name": value["axiom_report"]["declaration"] = "other"
    elif mutation == "unapproved_dependency": value["axiom_report"]["axioms"] = ["unapproved_axiom"]
    elif mutation == "missing_typecheck": value["expected_proposition_checked"] = False
    elif mutation == "wrong_proposition_digest": value["expected_proposition_digest"] = "a"*64
    elif mutation == "missing_compiled_source": value["compiled_source_digest"] = ""
    elif mutation == "wrong_source": value["source_binding"]["source_digest"] = "a"*64
    elif mutation == "wrong_proof": value["generated_proof"] += " changed"
    elif mutation == "wrong_toolchain_policy": value["toolchain"]["metadata"]["approved_axioms"] = ["unapproved_axiom"]
    elif mutation == "missing_report_position": value["axiom_report"]["source_line"] = None
    elif mutation == "unknown_field": value["unbound_authority"] = True
    elif mutation == "legacy_schema": value["schema_version"] = "lean-kernel-receipt/v1"
    elif mutation == "missing_source": value["submitted_source"] = ""
    elif mutation == "wrong_submitted_source": value["submitted_source"] += "-- changed source\n"
    elif mutation == "wrong_compiled_recipe": value["compiled_source_digest"] = "a"*64
    elif mutation == "wrong_selected_declaration":
        value["theorem_name"] = "other";value["axiom_report"]["declaration"] = "other"
    elif mutation == "wrong_report_line": value["axiom_report"]["source_line"] += 1
    elif mutation == "empty_report_text": value["axiom_report"]["report_text"] = ""
    elif mutation == "wrong_declaration_report_text": value["axiom_report"]["report_text"] = "'other' does not depend on any axioms"
    elif mutation == "hidden_sorry_report_text": value["axiom_report"]["report_text"] = "'wanted' depends on axioms: [sorryAx]"
    elif mutation == "hidden_dependency_report_text": value["axiom_report"]["report_text"] = "'wanted' depends on axioms: [unapproved_axiom]"
    value["receipt_id"] = "lean-kernel-receipt:" + stable_digest({k:v for k,v in value.items() if k!="receipt_id"})
    with pytest.raises((LeanKernelError,ValueError)):
        LeanKernelReceipt.from_dict(value)


def test_lean_v2_receipt_rejects_changed_supplied_identity():
    outcome, _, _ = _bound_lean_outcome()
    value=outcome.receipt.to_dict();value["receipt_id"]="lean-kernel-receipt:"+"a"*64
    with pytest.raises(LeanKernelError): LeanKernelReceipt.from_dict(value)


def test_lean_source_only_compilation_cannot_prove_an_opaque_request_obligation():
    runner, _ = _process_runner(_axiom_message("'wanted' does not depend on any axioms"))
    backend=LeanKernelBackend(native_identity_probe=_fictional_native_identity, runner=runner,native_probe=lambda:_available_native("lean","lean"))
    outcome=backend.run(_request(family="lean4",encoding="lean4",source="theorem wanted : True := by trivial\n"))
    assert outcome.result.status is ResultStatus.CANDIDATE
    assert outcome.receipt.accepted is False and outcome.receipt.expected_proposition_checked is False
    assert outcome.result.witness["candidate_kind"] == "source_only_lean_declaration"


def test_lean_explicit_namespaced_target_is_not_replaced_by_first_theorem():
    source="theorem decoy : True := by trivial\nnamespace Law\ntheorem wanted : True := by trivial\nend Law\n"
    outcome, _, _ = _bound_lean_outcome(source=source,name="Law.wanted")
    assert outcome.receipt.theorem_name=="Law.wanted" and outcome.result.status is ResultStatus.PROVED
    assert "theorem wanted" in outcome.receipt.generated_proof and "theorem decoy" not in outcome.receipt.generated_proof
    with pytest.raises(LeanKernelError): _bound_lean_outcome(source=source,name="absent")


@pytest.mark.parametrize("source", [
    "private axiom forbidden : False\ntheorem wanted : False := forbidden\n",
    "#print \"'wanted' does not depend on any axioms\"\ntheorem wanted : True := by trivial\n",
    "macro \"cheat\" : term => `(by sorry)\ntheorem wanted : True := cheat\n",
])
def test_lean_source_hazards_never_reach_a_runner(source):
    runner, calls = _process_runner(_axiom_message("'wanted' does not depend on any axioms"))
    backend=LeanKernelBackend(native_identity_probe=_fictional_native_identity, runner=runner,native_probe=lambda:_available_native("lean","lean"))
    outcome=backend.run(_request(family="lean4",encoding="lean4",source=source,
        expected_declaration="wanted",expected_proposition="False" if "False" in source else "True"))
    assert outcome.receipt.accepted is False and calls==[]


def test_lean_source_comments_and_strings_are_diagnostics_not_elaborated_axioms():
    source='/- sorry /- admit -/ axiom -/\ndef text : String := "sorry admit axiom"\ntheorem wanted : True := by trivial\n'
    assert scan_lean_incomplete_or_unsafe(source)==()
    outcome, _, _ = _bound_lean_outcome(source=source)
    assert outcome.result.status is ResultStatus.PROVED


@pytest.mark.parametrize("term", ["_","?goal","True) := True.intro","(True","by exact True","True -- escape"])
def test_lean_expected_goal_is_complete_and_cannot_inject_commands(term):
    with pytest.raises(LeanKernelError): _bound_lean_outcome(proposition=term)


def test_lean_request_payload_cannot_self_approve_a_dependency():
    from dataclasses import replace
    runner, _ = _process_runner(_axiom_message("'wanted' depends on axioms: [unapproved_axiom]"))
    backend=LeanKernelBackend(native_identity_probe=_fictional_native_identity, runner=runner,native_probe=lambda:_available_native("lean","lean"))
    request=_request(family="lean4",encoding="lean4",source="theorem wanted : True := by trivial\n",
        expected_declaration="wanted",expected_proposition="True")
    request=replace(request,payload=FrozenMap({**request.payload.to_dict(),"approved_axioms":["unapproved_axiom"]}))
    outcome=backend.run(request)
    assert outcome.receipt.accepted is False and outcome.receipt.approved_axioms==()


@pytest.mark.skipif(os.environ.get("IPFS_DATASETS_RUN_NATIVE_LEAN") != "1",reason="explicit native Lean resource authorization required")
def test_lean_native_v2_expected_type_and_dependency_policy(tmp_path):
    """Actual compiler checks; opt-in CI host only, never a mocked native claim."""
    from ipfs_datasets_py.logic.backends.resource_admission import ResourceAdmittedToolRunner
    executable=os.environ.get("IPFS_DATASETS_LEAN_EXECUTABLE","")
    version=os.environ.get("IPFS_DATASETS_LEAN_VERSION","4.34.1")
    assert executable and Path(executable).is_absolute() and Path(executable).is_file()
    runner=ResourceAdmittedToolRunner(cpu_slots=1,child_process_slots=1)
    probe=runner.run(ToolRunRequest(argv=(executable,"--version"),limits=ToolRunLimits(
        timeout_seconds=15,cpu_seconds=15,memory_bytes=4*1024**3,resident_memory_bytes=512*1024**2,
        max_output_bytes=65536,max_input_bytes=65536,max_workspace_bytes=65536)))
    assert probe.ok and probe.native_lifecycle is not None
    assert re.search(r"\bversion\s+"+re.escape(version)+r"\b",probe.stdout)
    backend=LeanKernelBackend(executable=executable,backend_version=version,runner=runner)
    cases=[("positive","theorem wanted (p q : Prop) : p ∧ q → q ∧ p := by\n  intro h\n  exact And.intro h.right h.left\n","∀ (p q : Prop), p ∧ q → q ∧ p"),
        ("wrong_type","theorem wanted : True := by trivial\n","False"),
        ("unapproved_dependency","import Init.Classical\ntheorem wanted (p : Prop) : p ∨ ¬ p := Classical.em p\n","∀ (p : Prop), p ∨ ¬ p")]
    rows=[]
    for name,source,proposition in cases:
        outcome=backend.run(_request(family="lean4",encoding="lean4",source=source,
            expected_declaration="wanted",expected_proposition=proposition,
            bounds=ExecutionBounds(timeout_ms=30000,max_steps=100,max_memory_bytes=512*1024**2,max_output_bytes=65536)))
        rows.append({"case":name,"outcome":outcome.to_dict()})
        if name=="positive": assert outcome.result.status is ResultStatus.PROVED and outcome.receipt.accepted
        else: assert outcome.result.status is not ResultStatus.PROVED and not outcome.receipt.accepted
        if name=="unapproved_dependency": assert outcome.receipt.axiom_report is not None and outcome.receipt.axiom_report.axioms
    report={"schema":"native-lean-v2-proof-binding-check/v1","native_Lean_executed":True,
        "toolchain_version":version,"version_probe":probe.to_dict(),"cases":rows,
        "statutory_or_source_semantic_admission":False}
    destination=Path(os.environ.get("IPFS_DATASETS_NATIVE_LEAN_REPORT",str(tmp_path/"native-lean-v2-result.json")))
    destination.write_text(json.dumps(report,sort_keys=True,indent=2)+"\n",encoding="utf-8")


@pytest.mark.parametrize("customization", [
    'local notation "False" => True',
    'notation "False" => True',
    'infix:50 " === " => Eq',
    'prefix:50 "False" => id',
    'postfix:50 "!" => id',
    'attribute [simp] True.intro',
    'instance : Decidable True := isTrue True.intro',
    'set_option autoImplicit true',
    'open scoped Classical',
    'open Classical',
    'scoped notation "False" => True',
    'variable (False : Prop)',
    '@[simp]',
])
def test_lean_source_cannot_customize_the_requested_proposition_environment(customization):
    source=customization+"\ntheorem wanted : True := by trivial\n"
    runner,calls=_process_runner(_axiom_message("'wanted' does not depend on any axioms"))
    backend=LeanKernelBackend(native_identity_probe=_fictional_native_identity, runner=runner,native_probe=lambda:_available_native("lean","lean"))
    outcome=backend.run(_request(family="lean4",encoding="lean4",source=source,
        expected_declaration="wanted",expected_proposition="False"))
    assert outcome.result.status is ResultStatus.MALFORMED
    assert outcome.receipt.accepted is False and calls==[]
    assert "lean_source_contains_unsupported_metaprogramming_or_output" in outcome.receipt.diagnostics


@pytest.mark.parametrize("customization", ['local notation "False" => True','set_option autoImplicit true','private axiom forbidden : False'])
def test_lean_v2_replay_cannot_bypass_the_source_customization_policy(customization):
    from ipfs_datasets_py.logic.backends.kernel import lean
    from ipfs_datasets_py.logic.backends.kernel.wasm import KernelSourceTreeBinding
    outcome,_,_=_bound_lean_outcome()
    value=outcome.receipt.to_dict()
    source=customization+"\n"+value["submitted_source"]
    proof=lean.extract_generated_proof(source,"wanted")
    compiled=lean.instrument_lean_source_for_axioms(source,"wanted",expected_proposition="True")
    value.update(submitted_source=source,theorem_digest=lean.content_digest(source),
        generated_proof=proof,generated_proof_digest=lean.content_digest(proof),compiled_source_digest=lean.content_digest(compiled),
        source_tree=KernelSourceTreeBinding.from_files({"Main.lean":source},primary_path="Main.lean").to_dict())
    value["source_binding"]["source_digest"]=lean.content_digest(source)
    guard=lean.lean_expected_obligation_declaration(source,"wanted","True")
    value["expected_obligation_declaration"]=guard
    value["axiom_report"].update(declaration=guard,report_text="'"+guard+"' does not depend on any axioms")
    value["axiom_report"]["source_line"]=compiled[:compiled.rfind("#print axioms")].count("\n")+1
    value["receipt_id"]="lean-kernel-receipt:"+stable_digest({k:v for k,v in value.items()if k!="receipt_id"})
    with pytest.raises(LeanKernelError): LeanKernelReceipt.from_dict(value)


@pytest.mark.parametrize("header", ["import Init", "import Init Init.Classical", "import Init.Prelude\nimport Init.Classical"])
def test_lean_trusted_import_headers_are_complete_and_bound(header):
    from ipfs_datasets_py.logic.backends.kernel import lean
    outcome,calls,_=_bound_lean_outcome(source=header+"\ntheorem wanted : True := by trivial\n")
    assert calls and outcome.result.status is ResultStatus.PROVED
    assert outcome.receipt.imports == lean.extract_lean_imports(outcome.receipt.submitted_source)
    assert outcome.receipt.approved_imports == lean.LEAN_DEFAULT_APPROVED_IMPORTS
    assert outcome.receipt.axiom_policy_digest == lean.lean_axiom_policy_digest(())
    assert LeanKernelReceipt.from_dict(outcome.receipt.to_dict()).accepted


@pytest.mark.parametrize("header", ["import Unreviewed", "import Init Unreviewed", "import Main"])
def test_lean_unapproved_imports_never_reach_the_compiler(header):
    outcome,calls,_=_bound_lean_outcome(source=header+"\ntheorem wanted : True := by trivial\n")
    assert not calls and not outcome.receipt.accepted
    assert outcome.result.status is not ResultStatus.PROVED
    assert "lean_source_contains_unapproved_import" in outcome.receipt.diagnostics


@pytest.mark.parametrize("header", ["public import Init", "meta import Init", "import", "import Init, Init.Classical", "import Init\nimport Init", "import «Init»"])
def test_lean_unsupported_import_syntax_is_explicit(header):
    from ipfs_datasets_py.logic.backends.kernel import lean
    with pytest.raises(LeanKernelError):
        lean.extract_lean_imports(header+"\ntheorem wanted : True := by trivial\n")


def test_lean_non_header_import_is_explicit_and_payload_cannot_approve_modules():
    from ipfs_datasets_py.logic.backends.kernel import lean
    with pytest.raises(LeanKernelError):
        lean.extract_lean_imports("theorem wanted : True := by trivial\nimport Init\n")
    runner,calls=_process_runner(_axiom_message("'wanted' does not depend on any axioms"))
    source="import Unreviewed\ntheorem wanted : True := by trivial\n"
    request=_request(family="lean4",encoding="lean4",source=source,
                     expected_declaration="wanted",expected_proposition="True")
    from dataclasses import replace
    request=replace(request,payload=FrozenMap(dict(request.payload.to_dict(),approved_imports=["Unreviewed"])))
    outcome=LeanKernelBackend(native_identity_probe=_fictional_native_identity, runner=runner,native_probe=lambda:_available_native("lean","lean")).run(request)
    assert not calls and not outcome.receipt.accepted


@pytest.mark.parametrize("mutation", ["imports", "policy", "metadata", "shadow"])
def test_lean_v2_replay_rejects_import_lies_and_source_tree_shadowing(mutation):
    from ipfs_datasets_py.logic.backends.kernel import lean
    from ipfs_datasets_py.logic.backends.kernel.wasm import KernelSourceTreeBinding
    outcome,_,_=_bound_lean_outcome(source="import Init\ntheorem wanted : True := by trivial\n")
    value=outcome.receipt.to_dict()
    if mutation=="imports": value["imports"]=[]
    elif mutation=="policy": value["approved_imports"]=["Init"]
    elif mutation=="metadata": value["toolchain"]["metadata"]["approved_imports"]=[]
    else:
        value["source_tree"]=KernelSourceTreeBinding.from_files(
            {"Main.lean":value["submitted_source"],"Init.lean":"theorem fake : True := by trivial\n"},
            primary_path="Main.lean").to_dict()
    value["receipt_id"]="lean-kernel-receipt:"+stable_digest({k:v for k,v in value.items() if k!="receipt_id"})
    with pytest.raises(LeanKernelError): LeanKernelReceipt.from_dict(value)


@pytest.mark.parametrize("command", ["prelude", "module"])
def test_lean_core_environment_customization_is_refused(command):
    outcome,calls,_=_bound_lean_outcome(source=command+"\ntheorem wanted : True := by trivial\n")
    assert not calls and not outcome.receipt.accepted


def test_lean_trusted_import_configuration_is_pinned_in_the_policy():
    from ipfs_datasets_py.logic.backends.kernel import lean
    assert lean.lean_axiom_policy_digest(()) != lean.lean_axiom_policy_digest((),("Init",))
    assert LeanKernelBackend(native_identity_probe=_fictional_native_identity, approved_imports=("Init",)).approved_imports == ("Init",)
    with pytest.raises(LeanKernelError): LeanKernelBackend(native_identity_probe=_fictional_native_identity, approved_imports=("Main",))


def test_lean_dependency_report_uses_the_exact_relative_cli_input():
    outcome,calls,_=_bound_lean_outcome()
    assert len(calls)==1 and calls[0].argv[-1]=="Main.lean"
    assert outcome.result.status is ResultStatus.PROVED
    assert outcome.receipt.axiom_report.source_path=="Main.lean"
    # BoundedToolRunner intentionally preserves requested, not expanded argv.
    assert "{workspace}" not in outcome.receipt.axiom_report.source_path


@pytest.mark.parametrize("filename", ["Other.lean", "./Main.lean", "/unrelated/Main.lean", "{workspace}/Main.lean"])
def test_lean_dependency_report_cannot_use_another_or_equivalent_filename(filename):
    stdout=_axiom_message("'wanted' does not depend on any axioms",fileName=filename)
    outcome,calls,_=_bound_lean_outcome(stdout=stdout)
    assert calls and not outcome.receipt.accepted and outcome.receipt.axiom_report is None


def test_lean_v2_replay_requires_its_exact_compiler_input_filename():
    outcome,_,_=_bound_lean_outcome()
    value=outcome.receipt.to_dict()
    value["axiom_report"]["source_path"]="/unrelated/Main.lean"
    value["receipt_id"]="lean-kernel-receipt:"+stable_digest({k:v for k,v in value.items() if k!="receipt_id"})
    with pytest.raises(LeanKernelError): LeanKernelReceipt.from_dict(value)



def test_lean_v3_audits_instantiated_obligation_dependencies():
    source="import Init.Classical\ntheorem wanted {p : Prop} [h : Nonempty (Decidable p)] : Nonempty (Decidable p) := h\n"
    proposition="Nonempty (Decidable (∀ p : Prop, p ∨ ¬p))"
    from ipfs_datasets_py.logic.backends.kernel import lean
    guard=lean.lean_expected_obligation_declaration(source,"wanted",proposition)
    stdout=_axiom_message("'"+guard+"' depends on axioms: [propext, Classical.choice, Quot.sound]")
    outcome,calls,_=_bound_lean_outcome(source=source,proposition=proposition,stdout=stdout)
    assert calls and not outcome.receipt.accepted
    assert outcome.receipt.theorem_name=="wanted" and outcome.receipt.expected_obligation_declaration==guard
    assert outcome.receipt.axiom_report.declaration==guard
    assert "Classical.choice" in outcome.receipt.axiom_report.axioms


def test_lean_v3_clean_original_theorem_report_cannot_replace_guard_report():
    source="import Init.Classical\ntheorem wanted {p : Prop} [h : Nonempty (Decidable p)] : Nonempty (Decidable p) := h\n"
    proposition="Nonempty (Decidable (∀ p : Prop, p ∨ ¬p))"
    runner,calls=_process_runner(_axiom_message("'wanted' does not depend on any axioms"),adapt_guard_reports=False)
    outcome=LeanKernelBackend(native_identity_probe=_fictional_native_identity,runner=runner,
        native_probe=lambda:_available_native("lean","lean")).run(_request(family="lean4",encoding="lean4",source=source,
            expected_declaration="wanted",expected_proposition=proposition))
    assert calls and not outcome.receipt.accepted and outcome.receipt.axiom_report is None


def test_lean_v3_guard_identity_depends_on_complete_source_target_and_proposition():
    from ipfs_datasets_py.logic.backends.kernel import lean
    source="theorem wanted : True := by trivial\n"
    base=lean.lean_expected_obligation_declaration(source,"wanted","True")
    assert len({base,lean.lean_expected_obligation_declaration(source+"-- revision\n","wanted","True"),
        lean.lean_expected_obligation_declaration(source,"other","True"),
        lean.lean_expected_obligation_declaration(source,"wanted","False")})==4
    instrumented=lean.instrument_lean_source_for_axioms(source,"wanted",expected_proposition="True")
    assert "theorem "+base+" : (True) := _root_.wanted" in instrumented
    assert instrumented.endswith("#print axioms _root_."+base+"\n")


@pytest.mark.parametrize("mutation", ["missing_guard", "other_guard", "original_report", "identity_missing", "identity_unchecked",
    "changed_version", "changed_executable", "changed_executable_sha", "changed_size", "changed_stat", "failed_version",
    "stderr_version", "other_version_command", "identity_scope", "unknown_identity_field", "v2_schema"])
def test_lean_v3_replay_rejects_guard_and_native_identity_mutations(mutation):
    outcome,_,_=_bound_lean_outcome();value=outcome.receipt.to_dict()
    identity=value["native_identity"]
    if mutation=="missing_guard": value["expected_obligation_declaration"]=""
    elif mutation=="other_guard": value["expected_obligation_declaration"]="other"
    elif mutation=="original_report":
        value["axiom_report"].update(declaration="wanted",report_text="'wanted' does not depend on any axioms")
    elif mutation=="identity_missing": value["native_identity"]=None
    elif mutation=="identity_unchecked": value["native_identity_checked_after_compile"]=False
    elif mutation=="changed_version": identity["actual_version"]="other"
    elif mutation=="changed_executable": identity["resolved_executable"]="/other/lean"
    elif mutation=="changed_executable_sha": identity["executable_sha256"]="e"*64
    elif mutation=="changed_size": identity["executable_bytes"]=2
    elif mutation=="changed_stat": identity["executable_stat_after"]["mtime_ns"]+=1
    elif mutation=="failed_version": identity["version_returncode"]=1
    elif mutation=="stderr_version": identity["version_stderr"]="error"
    elif mutation=="other_version_command": identity["version_command"]=[identity["resolved_executable"],"--help"]
    elif mutation=="identity_scope": identity["library_scope"]="all libraries independently authenticated"
    elif mutation=="unknown_identity_field": identity["unreviewed"]=True
    else: value["schema_version"]="lean-kernel-receipt/v2"
    value["receipt_id"]="lean-kernel-receipt:"+stable_digest({k:v for k,v in value.items() if k!="receipt_id"})
    with pytest.raises(LeanKernelError): LeanKernelReceipt.from_dict(value)


def test_lean_v3_configured_version_mismatch_refuses_before_proof_execution():
    runner,calls=_process_runner(_axiom_message("'wanted' does not depend on any axioms"))
    backend=LeanKernelBackend(backend_version="different-configured-version",runner=runner,
        native_probe=lambda:_available_native("lean","lean"),native_identity_probe=_fictional_native_identity)
    outcome=backend.run(_request(family="lean4",encoding="lean4",source="theorem wanted : True := by trivial\n",
        expected_declaration="wanted",expected_proposition="True"))
    assert not calls and not outcome.receipt.accepted
    assert "does not match the observed native version" in outcome.result.reason


def test_lean_v3_default_availability_does_not_observe_version_or_run_a_process():
    import sys
    runner,calls=_process_runner("not executed")
    backend=LeanKernelBackend(executable=sys.executable,backend_version="declared-label",runner=runner)
    capability=backend.probe_capabilities()
    assert capability.native.available and capability.native.version==""
    assert capability.native.metadata["configured_version_label"]=="declared-label"
    assert capability.native.metadata["native_version_observed"] is False
    assert backend.is_available() and not calls


def test_lean_v3_identity_is_rechecked_after_compiler_execution():
    from dataclasses import replace
    identity=_fictional_native_identity();calls_to_identity=0
    def observe():
        nonlocal calls_to_identity
        calls_to_identity+=1
        return identity if calls_to_identity==1 else replace(identity,executable_sha256="e"*64)
    runner,calls=_process_runner(_axiom_message("'wanted' does not depend on any axioms"))
    backend=LeanKernelBackend(runner=runner,native_probe=lambda:_available_native("lean","lean"),native_identity_probe=observe)
    outcome=backend.run(_request(family="lean4",encoding="lean4",source="theorem wanted : True := by trivial\n",
        expected_declaration="wanted",expected_proposition="True"))
    assert calls and not outcome.receipt.accepted and not outcome.receipt.native_identity_checked_after_compile
    assert "native executable identity changed" in outcome.result.reason


def test_lean_v3_payload_cannot_supply_native_identity():
    from dataclasses import replace
    runner,calls=_process_runner(_axiom_message("'wanted' does not depend on any axioms"))
    request=_request(family="lean4",encoding="lean4",source="theorem wanted : True := by trivial\n",
        expected_declaration="wanted",expected_proposition="True")
    request=replace(request,payload=FrozenMap(dict(request.payload.to_dict(),native_identity={"actual_version":"injected"})))
    outcome=LeanKernelBackend(runner=runner,native_probe=lambda:_available_native("lean","lean"),
        native_identity_probe=_fictional_native_identity).run(request)
    assert calls and outcome.receipt.accepted and outcome.receipt.native_identity.actual_version=="test"
    assert outcome.receipt.native_identity.observation_kind=="trusted_fictional_identity_fixture"



def test_lean_v3_native_binary_digest_is_raw_bytes_and_detects_replacement(tmp_path):
    # Ordinary metadata file only; no executable or compiler is run.
    import hashlib
    from ipfs_datasets_py.logic.backends.kernel import lean
    path=tmp_path/"fictional-native-bytes"
    path.write_bytes(b"first fictional executable bytes")
    first=lean._native_executable_snapshot(str(path))
    assert first[1]==hashlib.sha256(path.read_bytes()).hexdigest()
    assert first[1]!=lean.content_digest(path.read_text())
    path.write_bytes(b"second fictional executable bytes")
    assert lean._native_executable_snapshot(str(path))!=first




def test_lean_v3_explicit_trusted_policy_applies_to_guard_dependencies():
    source="import Init.Classical\ntheorem wanted {p : Prop} [h : Nonempty (Decidable p)] : Nonempty (Decidable p) := h\n"
    proposition="Nonempty (Decidable (∀ p : Prop, p ∨ ¬p))"
    from ipfs_datasets_py.logic.backends.kernel import lean
    guard=lean.lean_expected_obligation_declaration(source,"wanted",proposition)
    approved=("Classical.choice","Quot.sound","propext")
    stdout=_axiom_message("'"+guard+"' depends on axioms: [propext, Classical.choice, Quot.sound]")
    outcome,_,_=_bound_lean_outcome(source=source,proposition=proposition,stdout=stdout,approved_axioms=approved)
    assert outcome.receipt.accepted and outcome.receipt.axiom_report.declaration==guard
    assert outcome.receipt.native_identity.observation_kind=="trusted_fictional_identity_fixture"



def test_lean_v3_precancelled_request_runs_no_identity_or_proof_callbacks():
    from types import SimpleNamespace
    calls_to_identity=[]
    runner,calls=_process_runner("not executed")
    def observe():
        calls_to_identity.append(True)
        return _fictional_native_identity()
    backend=LeanKernelBackend(runner=runner,native_probe=lambda:_available_native("lean","lean"),native_identity_probe=observe)
    outcome=backend.run(_request(family="lean4",encoding="lean4",source="theorem wanted : True := by trivial\n",
        expected_declaration="wanted",expected_proposition="True"),cancellation=SimpleNamespace(cancelled=True))
    assert not calls and not calls_to_identity and not outcome.receipt.accepted
    assert outcome.result.status is ResultStatus.ERROR and "cancelled" in outcome.result.reason


def test_lean_v3_depleted_remaining_budget_never_starts_identity_or_proof(monkeypatch):
    from types import SimpleNamespace
    from ipfs_datasets_py.logic.backends.kernel import lean
    ticks=iter((0.0,0.3))
    monkeypatch.setattr(lean,"time",SimpleNamespace(monotonic=lambda:next(ticks,0.3)))
    identities=[]
    def observe():
        identities.append(True)
        return _fictional_native_identity()
    runner,calls=_process_runner("not executed")
    backend=LeanKernelBackend(runner=runner,native_probe=lambda:_available_native("lean","lean"),native_identity_probe=observe)
    outcome=backend.run(_request(family="lean4",encoding="lean4",source="theorem wanted : True := by trivial\n",
        expected_declaration="wanted",expected_proposition="True"))
    assert not identities and not calls and not outcome.receipt.accepted
    assert outcome.result.status is ResultStatus.TIMEOUT and "deadline" in outcome.result.reason


def test_lean_v3_version_probe_receives_existing_cancellation_signal(tmp_path):
    # An explicitly modeled runner; no process, version binary or Lean is run.
    from dataclasses import replace
    from types import SimpleNamespace
    signal=SimpleNamespace(cancelled=False)
    class ModeledRunner(BoundedToolRunner):
        def __init__(self):
            super().__init__();self.calls=[]
        def run(self,request,**kwargs):
            self.calls.append((request,kwargs))
            assert kwargs.get("cancellation") is signal
            signal.cancelled=True
            return replace(_lean_output(""),cancelled=True,error="cancelled modeled version probe")
    path=tmp_path/"not-an-executed-version-binary";path.write_bytes(b"ordinary metadata fixture");path.chmod(0o700)
    runner=ModeledRunner()
    backend=LeanKernelBackend(executable=str(path),runner=runner,
        native_probe=lambda:_available_native("lean",str(path)))
    outcome=backend.run(_request(family="lean4",encoding="lean4",source="theorem wanted : True := by trivial\n",
        expected_declaration="wanted",expected_proposition="True"),cancellation=signal)
    assert len(runner.calls)==1 and runner.calls[0][0].argv[-1]=="--version"
    assert not outcome.receipt.accepted and outcome.result.status is ResultStatus.ERROR



def test_lean_v3_version_and_compiler_share_the_original_output_and_plain_runner_AS_bound(tmp_path):
    # Explicit modeled version/compiler output; ordinary file metadata only.
    # This establishes neither native Lean execution nor an accepted proof.
    from dataclasses import replace
    from ipfs_datasets_py.logic.backends.kernel import lean
    source="theorem wanted : True := by trivial\n";proposition="True";cap=2048
    guard=lean.lean_expected_obligation_declaration(source,"wanted",proposition)
    compiled=lean.instrument_lean_source_for_axioms(source,"wanted",expected_proposition=proposition)
    line=compiled[:compiled.rfind("#print axioms")].count("\n")+1
    version="Lean (version test)\n"
    report=_axiom_message("'"+guard+"' does not depend on any axioms",fileName="Main.lean",pos={"line":line,"column":0})
    extra=_axiom_message("")
    target=cap-len(version.encode())//2
    filler="x"*(target-len(report.encode())-len(extra.encode()))
    compiler=report+_axiom_message(filler)
    assert len(compiler.encode())<=cap<len(version.encode())+len(compiler.encode())
    class ModeledRunner(BoundedToolRunner):
        def __init__(self): super().__init__();self.calls=[]
        def run(self,request,**kwargs):
            self.calls.append(request)
            output=version if request.argv[-1]=="--version" else compiler
            return replace(_lean_output(output),command=tuple(request.argv))
    path=tmp_path/"not-an-executed-compiler";path.write_bytes(b"ordinary metadata fixture");path.chmod(0o700)
    runner=ModeledRunner();bounds=ExecutionBounds(timeout_ms=2000,max_output_bytes=cap,max_memory_bytes=64*1024**2)
    outcome=LeanKernelBackend(executable=str(path),runner=runner,native_probe=lambda:_available_native("lean",str(path))).run(
        _request(family="lean4",encoding="lean4",source=source,expected_declaration="wanted",expected_proposition=proposition,bounds=bounds))
    assert len(runner.calls)==2
    assert runner.calls[0].limits.memory_bytes==bounds.max_memory_bytes
    assert runner.calls[1].limits.max_output_bytes==cap-len(version.encode())
    assert not outcome.receipt.accepted and outcome.result.status is ResultStatus.ERROR
    assert outcome.result.usage.output_bytes>cap and "aggregate" in outcome.result.reason



def test_lean_v3_version_output_charge_preserves_complete_source_input_capacity():
    # Fictional identity and authored compiler output only; no native facts.
    from ipfs_datasets_py.logic.backends.kernel import lean
    cap=4096;version_cost=128;target=cap-64
    prefix="theorem wanted : True := by trivial\n-- "
    minimal=prefix+"x\n"
    padding=target-len(lean.instrument_lean_source_for_axioms(minimal,"wanted",expected_proposition="True").encode())
    source=prefix+"x"*(padding+1)+"\n"
    compiled=lean.instrument_lean_source_for_axioms(source,"wanted",expected_proposition="True")
    assert cap-version_cost<len(compiled.encode())==target<=cap
    class FictionalVersionCostBackend(LeanKernelBackend):
        def _observe_native_identity(self,bounds=None,**kwargs):
            kwargs["observation_usage"]["output_bytes"]=version_cost
            return super()._observe_native_identity(bounds,**kwargs)
    runner,calls=_process_runner(_axiom_message("'wanted' does not depend on any axioms"))
    backend=FictionalVersionCostBackend(runner=runner,native_probe=lambda:_available_native("lean","lean"),
        native_identity_probe=_fictional_native_identity)
    outcome=backend.run(_request(family="lean4",encoding="lean4",source=source,
        expected_declaration="wanted",expected_proposition="True",bounds=ExecutionBounds(timeout_ms=2000,max_output_bytes=cap)))
    assert calls and outcome.receipt.accepted
    assert calls[0].limits.max_input_bytes==cap
    assert calls[0].limits.max_output_bytes==cap-version_cost
    assert outcome.receipt.submitted_source==source


# Historical fixture pins: 158b5f0c0a25ea42778f0a718477eaa0a6b8c4f053f3987ef3cd8e5517f82b23
# before 51d2c414, then 27ede074ceb68cd91d50eada99b9c6f02216607e22610bc63db4fde69e17fb4c.
# Current reviewed constructors explicitly bind the current verifier profile;
# negative cache controls changed the complete owner. This pin never follows edits itself.
_NATIVE_PROOF_CACHE_FIXTURE_SHA256 = "4e012101e4400324175c02d296b51abde97d065c76abfddef1b51d16329f639d"


def _load_native_proof_cache_fixture_owner():
    """Load exact pinned fixture bytes; execute no fixture/kernel helper.

    This distinct fixture-only module does not claim canonical package identity.
    Compiling the verified buffer avoids accepting a stale bytecode cache as
    evidence of the source whose pre/post bytes were checked.
    """
    import hashlib
    import importlib.util

    fixture_path = Path(__file__).resolve().parents[3] / "unit/logic/legal_ir/test_proof_cache.py"
    assert fixture_path.is_file() and not fixture_path.is_symlink()
    raw = fixture_path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == _NATIVE_PROOF_CACHE_FIXTURE_SHA256, "native proof-cache fixture source pin differs before import"
    fixture_spec = importlib.util.spec_from_file_location("_native_lean_cache_fixture_owner", fixture_path)
    assert fixture_spec is not None and fixture_spec.loader is not None
    fixture_owner = importlib.util.module_from_spec(fixture_spec)
    exec(compile(raw, str(fixture_path), "exec", dont_inherit=True), fixture_owner.__dict__)
    assert fixture_owner.__name__ == fixture_spec.name == "_native_lean_cache_fixture_owner"
    assert fixture_owner.__spec__ is fixture_spec
    assert fixture_owner.__file__ == fixture_spec.origin == str(fixture_path)
    assert fixture_owner.__loader__ is fixture_spec.loader
    assert hashlib.sha256(fixture_path.read_bytes()).hexdigest() == _NATIVE_PROOF_CACHE_FIXTURE_SHA256, "native proof-cache fixture source changed during import"
    return fixture_owner


def _assert_lean_native_v3_proof_cache_round_trip(
    tmp_path, *, runner, processes, executable, version, bounds
):
    """Real Native3/cache checks; caller owns admission and process observation."""
    from dataclasses import replace

    from ipfs_datasets_py.logic.backends.process import SubprocessExecutor
    from ipfs_datasets_py.logic.ir_core.claims import Assumption, IRClaim, ProofObligation
    from ipfs_datasets_py.logic.ir_core.protocols import (
        AttemptStatus, AuthorityKind, BackendAttempt, ProofReceipt, ProofResult,
        ResultAuthority as ProtocolResultAuthority,
    )
    from ipfs_datasets_py.logic.legal_ir.proof_cache import (
        LEGAL_BOUND_PROOF_RECORD_SCHEMA_VERSION, LEGAL_PROOF_CONTEXT_SCHEMA_VERSION,
        LegalProofCache, LegalProofCacheError, LegalProofIntegrityError,
        build_legal_proof_binding,
    )
    fixture_owner = _load_native_proof_cache_fixture_owner()

    # The local SDK controller supplies the already-admitted ordinary runner;
    # the standalone wrapper below supplies the existing admitted runner. This
    # helper never creates a lease, adapts a foreign parent, or fakes execution.
    assert isinstance(runner, BoundedToolRunner)
    assert type(runner._executor) is SubprocessExecutor
    assert type(processes) is list and not processes
    assert executable and Path(executable).is_absolute() and Path(executable).is_file()
    assert isinstance(bounds, ExecutionBounds)
    assert 0 < bounds.timeout_ms <= 30000 and 0 < bounds.max_memory_bytes <= 4 * 1024**3
    assert 0 < bounds.max_output_bytes <= 65536 and 0 < bounds.max_steps <= 100
    backend = LeanKernelBackend(executable=executable, backend_version=version, runner=runner)
    source = "theorem cache_native_fixture : True := by trivial\n"
    # Discover the actual canonical toolchain profile before binding it into
    # the request. This is a real positive compile, not an injected identity
    # or a hand-built copy of the backend's resource/toolchain machinery.
    profile_outcome = backend.run(_request(family="lean4", encoding="lean4", source=source,
        expected_declaration="cache_native_fixture", expected_proposition="True", bounds=bounds))
    assert profile_outcome.result.status is ResultStatus.PROVED and profile_outcome.receipt.accepted
    assert profile_outcome.receipt.native_identity.actual_version == version

    artifact = fixture_owner._legal_artifact(fixture_owner._reviewed_fixture(
        sample_id="fictional-native-cache-provision", citation="FICTIONAL Test Act 1", section="1",
        text="A fictional agency shall publish a fictional notice."))
    source_ref = artifact.source_map.sources[0].ref_id
    assumption = Assumption("assumption:fictional-native-cache", "True", source_refs=(source_ref,))
    obligation = ProofObligation("obligation:fictional-native-cache", "True",
        assumption_ids=(assumption.assumption_id,), logic_family="lean4", source_refs=(source_ref,),
        metadata={"fixture_only": True, "statutory_meaning_claimed": False})
    artifact = replace(artifact, assumptions=(assumption,), proof_obligations=(obligation,))
    context = dict(schema_version=LEGAL_PROOF_CONTEXT_SCHEMA_VERSION, jurisdiction="fictional",
        interpretation_digest=stable_digest({"fictional_interpretation": 1}),
        dependency_versions={"fictional-definition": stable_digest({"definition": 1})},
        backend_id="lean", backend_version=version, toolchain=profile_outcome.receipt.toolchain.to_dict(),
        expected_declaration="cache_native_fixture", expected_proposition="True",
        axiom_policy_digest=profile_outcome.receipt.axiom_policy_digest)
    claim = IRClaim(claim_id="claim:fictional-native-cache", declaration_id=artifact.declaration_id,
        statement="True", assumptions=artifact.assumptions, obligations=(obligation,), domain="legal",
        source_refs=(source_ref,), metadata={"artifact_digest": artifact.digest,
            "source_digest": artifact.declaration_digest, "proof_context_digest": stable_digest(context)})
    request = BackendRequest.for_claim(claim, obligation.obligation_id,
        request_id="request:fictional-native-cache", requested_backend_id="lean", bounds=bounds,
        payload={"encoding": "lean4", "source": source, "expected_declaration": "cache_native_fixture",
            "expected_proposition": "True", "legal_proof_context": context})
    outcome = backend.run(request)
    assert outcome.result.status is ResultStatus.PROVED and outcome.receipt.accepted
    assert outcome.receipt.toolchain.to_dict() == context["toolchain"]
    assert outcome.receipt.request_digest == request.digest
    assert outcome.receipt.native_identity_checked_after_compile
    assert outcome.receipt.axiom_report.axioms == ()
    attempt = BackendAttempt(attempt_id="attempt:fictional-native-cache", request_digest=request.digest,
        backend_id="lean", backend_version=version, status=AttemptStatus.SUCCEEDED,
        bounds=request.bounds, usage=outcome.result.usage, output_digest=stable_digest(outcome.to_dict()))
    result = ProofResult.for_attempt(request, attempt, result_id="result:fictional-native-cache",
        authority=ProtocolResultAuthority(kind=AuthorityKind.THEOREM_PROOF, issuer="native-cache-integration",
            method="actual-Lean-kernel/v3", scope_digest=request.digest,
            configuration_digest=stable_digest(context)), status=outcome.result.status,
        payload={"kernel_receipt": outcome.receipt.to_dict(), "fictional_source_fixture_only": True})
    receipt = ProofReceipt.issue(claim, request, attempt, result,
        receipt_id="receipt:fictional-native-cache", verifier="native-cache-integration")
    binding = build_legal_proof_binding(artifact, receipt, claim=claim, request=request,
        attempt=attempt, result=result, context=context)

    assert len(processes) == 3
    assert sum(row["command"][-1:] == ["--version"] for row in processes) == 1
    assert sum(row["command"][-2:] == ["--json", "Main.lean"] for row in processes) == 2
    before_reuse = len(processes)
    profile = "fictional-native-cache-v3"
    cache_root = tmp_path / "native-proof-cache"
    record = LegalProofCache(root=cache_root).put(artifact, profile=profile, jurisdiction="fictional",
        theorem_receipts=(receipt,), proof_bindings=(binding,))
    assert record.schema_version == LEGAL_BOUND_PROOF_RECORD_SCHEMA_VERSION
    assert (cache_root / "records" / (record.content_cid + ".json")).is_file()
    disk = LegalProofCache(root=cache_root)
    loaded = disk.get(record.content_cid)
    assert loaded.to_dict() == record.to_dict()
    assert disk.get_by_source_digest(artifact.declaration_digest, profile=profile).content_cid == record.content_cid
    assert loaded.theorem_receipt_results(expected_context=context,
        obligation_id=obligation.obligation_id) == (receipt,)
    with pytest.raises(LegalProofCacheError, match="expected_context"):
        loaded.theorem_receipt_results()
    with pytest.raises(LegalProofIntegrityError, match="expected reuse context"):
        loaded.theorem_receipt_results(expected_context=context, obligation_id="obligation:another")
    with pytest.raises(LegalProofCacheError):
        disk.get_by_source_digest("sha256:" + "fa" * 32, profile=profile)
    with pytest.raises(LegalProofCacheError):
        disk.get_by_source_digest(artifact.declaration_digest, profile="another-profile")
    with pytest.raises(LegalProofCacheError):
        disk.put(loaded, profile="another-profile")

    rejected_artifact_facets = []
    for facet, changed in (
        ("source", replace(artifact, declaration_digest="sha256:" + "fa" * 32)),
        ("obligation", replace(artifact, proof_obligations=(replace(obligation, statement="False"),))),
        ("assumptions", replace(artifact, assumptions=(replace(assumption, statement="False"),))),
    ):
        with pytest.raises(LegalProofIntegrityError):
            disk.put(changed, profile=profile, jurisdiction="fictional",
                theorem_receipts=(receipt,), proof_bindings=(binding,))
        rejected_artifact_facets.append(facet)
    rejected_context_facets = []
    for facet in ("declaration", "proposition", "toolchain", "backend-profile", "interpretation", "dependency"):
        changed = copy.deepcopy(context)
        if facet == "declaration": changed["expected_declaration"] = "another_theorem"
        elif facet == "proposition": changed["expected_proposition"] = "False"
        elif facet == "toolchain": changed["toolchain"]["version"] = "another-native-version"
        elif facet == "backend-profile": changed["backend_version"] = "another-backend-profile"
        elif facet == "interpretation": changed["interpretation_digest"] = stable_digest({"fictional_interpretation": 2})
        else: changed["dependency_versions"]["fictional-definition"] = stable_digest({"definition": 2})
        with pytest.raises(LegalProofIntegrityError, match="expected reuse context"):
            loaded.theorem_receipt_results(expected_context=changed, obligation_id=obligation.obligation_id)
        rejected_context_facets.append(facet)
    assert loaded.theorem_receipt_results(expected_context=context, obligation_id=obligation.obligation_id) == (receipt,)
    assert disk.cids() == (record.content_cid,)
    assert len(processes) == before_reuse
    # These are coherently reissued SOFTWARE mutation controls over the real
    # returned Native receipt.  No mutated request is submitted to a backend.
    # All outer links agree on the advertised version; the checked toolchain
    # and actual executable version remain the original Native observation.
    original_evidence = copy.deepcopy({"artifact": artifact.to_dict(),
        "profile_outcome": profile_outcome.to_dict(), "bound_outcome": outcome.to_dict(),
        "context": context, "claim": claim.to_dict(), "request": request.to_dict(),
        "attempt": attempt.to_dict(), "result": result.to_dict(), "receipt": receipt.to_dict(),
        "binding": binding, "cache_record": loaded.to_dict()})
    original_process_results = copy.deepcopy(processes)
    reissued_backend_version_controls = []
    for advertised_version in ("other-version", "lean4"):
        assert advertised_version != version
        changed_context = copy.deepcopy(context)
        changed_context["backend_version"] = advertised_version
        changed_claim = replace(claim, metadata={**claim.metadata.to_dict(),
            "proof_context_digest": stable_digest(changed_context)})
        changed_payload = request.payload.to_dict()
        changed_payload["legal_proof_context"] = copy.deepcopy(changed_context)
        changed_request = BackendRequest.for_claim(changed_claim, request.obligation_id,
            request_id="request:software-reissued-native-cache-version:" + advertised_version,
            requested_backend_id="lean", bounds=request.bounds, payload=changed_payload)
        changed_source_binding = outcome.receipt.source_binding.bind(changed_request, source)
        changed_kernel = replace(outcome.receipt, request_digest=changed_request.digest,
            source_binding=changed_source_binding)
        # This parser check reissues metadata only; its accepted field retains
        # the original source check, and establishes no new Native execution.
        assert LeanKernelReceipt.from_dict(changed_kernel.to_dict()) == changed_kernel
        assert changed_kernel.native_identity.to_dict() == outcome.receipt.native_identity.to_dict()
        assert changed_kernel.toolchain.to_dict() == context["toolchain"]
        assert changed_kernel.native_identity.actual_version == changed_kernel.toolchain.version == version
        assert changed_kernel.request_digest == changed_kernel.source_binding.request_digest == changed_request.digest
        assert changed_kernel.source_binding.source_digest == outcome.receipt.source_binding.source_digest
        changed_attempt = replace(attempt,
            attempt_id="attempt:software-reissued-native-cache-version:" + advertised_version,
            request_digest=changed_request.digest, backend_version=advertised_version,
            usage=replace(attempt.usage, elapsed_ms=0, steps=0, peak_memory_bytes=0, output_bytes=0),
            diagnostics=("Software-reissued mutation; no corresponding Native execution.",),
            output_digest=stable_digest({"software_reissued_kernel_receipt": changed_kernel.to_dict(),
                "original_native_receipt_id": outcome.receipt.receipt_id}))
        changed_result = ProofResult.for_attempt(changed_request, changed_attempt,
            result_id="result:software-reissued-native-cache-version:" + advertised_version,
            authority=replace(result.authority, issuer="software-mutation-control",
                method="software-reissued-actual-native-base/no-new-execution",
                scope_digest=changed_request.digest, configuration_digest=stable_digest(changed_context)),
            status=ResultStatus.PROVED, payload={"kernel_receipt": changed_kernel.to_dict(),
                "software_reissued_mutation_only": True, "new_native_execution": False,
                "original_native_receipt_id": outcome.receipt.receipt_id})
        changed_receipt = ProofReceipt.issue(changed_claim, changed_request, changed_attempt, changed_result,
            receipt_id="receipt:software-reissued-native-cache-version:" + advertised_version,
            verifier="software-mutation-control")
        assert changed_receipt.backend_version == changed_result.backend_version == changed_attempt.backend_version == changed_context["backend_version"]
        assert changed_claim.metadata["proof_context_digest"] == stable_digest(changed_context)
        assert changed_request.payload.to_dict()["legal_proof_context"] == changed_context
        assert changed_receipt.request_digest == changed_kernel.request_digest == changed_request.digest
        assert changed_receipt.backend_version != changed_kernel.native_identity.actual_version
        with pytest.raises(LegalProofIntegrityError, match="backend version") as rejected_version:
            build_legal_proof_binding(artifact, changed_receipt, claim=changed_claim, request=changed_request,
                attempt=changed_attempt, result=changed_result, context=changed_context)
        assert processes == original_process_results
        reissued_backend_version_controls.append({"kind": "software_reissued_actual_native_base",
            "advertised_backend_version": advertised_version, "actual_native_version": version,
            "original_native_receipt_id": outcome.receipt.receipt_id,
            "new_native_execution": False, "native_processes_added": 0,
            "cache_binding_rejected": True, "rejection": str(rejected_version.value),
            "context": changed_context, "claim": changed_claim.to_dict(), "request": changed_request.to_dict(),
            "kernel_receipt": changed_kernel.to_dict(), "attempt": changed_attempt.to_dict(),
            "result": changed_result.to_dict(), "receipt": changed_receipt.to_dict()})
    assert original_evidence == {"artifact": artifact.to_dict(),
        "profile_outcome": profile_outcome.to_dict(), "bound_outcome": outcome.to_dict(),
        "context": context, "claim": claim.to_dict(), "request": request.to_dict(),
        "attempt": attempt.to_dict(), "result": result.to_dict(), "receipt": receipt.to_dict(),
        "binding": binding, "cache_record": loaded.to_dict()}
    assert loaded.theorem_receipt_results(expected_context=context, obligation_id=obligation.obligation_id) == (receipt,)
    assert disk.cids() == (record.content_cid,)
    assert processes == original_process_results and len(processes) == before_reuse == 3
    report = {"schema": "native-lean-v3-proof-cache-integration/v1", "native_Lean_executed": True,
        "compiler_output_mocked": False, "actual_process_results": processes,
        "profile_discovery_outcome": profile_outcome.to_dict(), "bound_outcome": outcome.to_dict(),
        "claim": claim.to_dict(), "request": request.to_dict(), "attempt": attempt.to_dict(),
        "result": result.to_dict(), "receipt": receipt.to_dict(), "proof_binding": binding,
        "cache_record_cid": record.content_cid, "disk_round_trip_and_exact_reuse_passed": True,
        "rejected_artifact_facets": rejected_artifact_facets, "rejected_context_facets": rejected_context_facets,
        "cache_source_profile_and_obligation_mismatches_rejected": True,
        "native_processes_during_reuse_or_mismatch_checks": len(processes) - before_reuse,
        "backend_version_mutation_controls": reissued_backend_version_controls,
        "software_reissued_backend_version_control_count": len(reissued_backend_version_controls),
        "actual_cache_native_command_count": len(processes),
        "actual_native_commands_for_version_mutation_controls": 0,
        "version_mutation_controls_are_new_native_results": False,
        "fictional_source_fixture_only": True, "statutory_meaning_or_corpus_admission": False,
        "resource_admission_scope": "caller_owned_not_established_by_this_helper",
        "outer_resource_closure_asserted": False, "pytest_case_credit_claimed_by_helper": 0}
    (tmp_path / "native-lean-proof-cache-v3.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return report


@pytest.mark.skipif(
    os.environ.get("IPFS_DATASETS_RUN_NATIVE_LEAN") != "1",
    reason="explicit native Lean resource authorization required",
)
def test_lean_native_v3_proof_cache_round_trip_and_exact_reuse_context(tmp_path):
    """Standalone opt-in CI route; separate from the local SDK caller-owned route."""
    from ipfs_datasets_py.logic.backends.resource_admission import ResourceAdmittedToolRunner

    processes = []

    class ObservedNativeRunner(ResourceAdmittedToolRunner):
        def run(self, request, **kwargs):
            result = super().run(request, **kwargs)
            assert result.native_lifecycle is not None
            processes.append(result.to_dict())
            return result

    runner = ObservedNativeRunner(cpu_slots=1, child_process_slots=1,
        workspace_root=tmp_path / "standalone-native-workspaces")
    _assert_lean_native_v3_proof_cache_round_trip(tmp_path, runner=runner, processes=processes,
        executable=os.environ.get("IPFS_DATASETS_LEAN_EXECUTABLE", ""),
        version=os.environ.get("IPFS_DATASETS_LEAN_VERSION", "4.34.1"),
        bounds=ExecutionBounds(timeout_ms=30000, max_steps=100,
            max_memory_bytes=512 * 1024**2, max_output_bytes=65536))



def test_lean_quoted_identifier_preserves_active_command_policy():
    """Quoted names are tokens, not string delimiters around later commands."""
    source = ('def «name"left» : Nat := 0\n'
              'set_option autoImplicit true\n'
              'def «name"right» : Nat := 0\n'
              'theorem wanted : True := by trivial\n')
    outcome, calls, _ = _bound_lean_outcome(source=source, proposition="True")
    assert outcome.result.status is ResultStatus.MALFORMED
    assert outcome.receipt.accepted is False and calls == []
    assert "lean_source_contains_unsupported_metaprogramming_or_output" in outcome.receipt.diagnostics


@pytest.mark.skipif(os.environ.get("IPFS_DATASETS_RUN_NATIVE_LEAN") != "1",
                    reason="explicit native Lean resource authorization required")
def test_lean_native_quoted_identifier_preserves_expected_goal(tmp_path):
    """Use the existing real kernel boundary; simulated reports cannot qualify this case."""
    from ipfs_datasets_py.logic.backends.resource_admission import ResourceAdmittedToolRunner
    executable = os.environ.get("IPFS_DATASETS_LEAN_EXECUTABLE", "")
    version = os.environ.get("IPFS_DATASETS_LEAN_VERSION", "4.34.1")
    assert executable and Path(executable).is_absolute() and Path(executable).is_file()
    source = ('def «name"left» : Nat := 0\n'
              'notation "False" => True\n'
              'def «name"right» : Nat := 0\n'
              'theorem wanted : True := by trivial\n')
    backend = LeanKernelBackend(executable=executable, backend_version=version,
        runner=ResourceAdmittedToolRunner(cpu_slots=1, child_process_slots=1))
    outcome = backend.run(_request(family="lean4", encoding="lean4", source=source,
        expected_declaration="wanted", expected_proposition="False",
        bounds=ExecutionBounds(timeout_ms=30000, max_steps=100,
            max_memory_bytes=512*1024**2, max_output_bytes=65536)))
    (tmp_path/"quoted-identifier-expected-goal-outcome.json").write_text(
        json.dumps({"schema": "lean-quoted-identifier-goal-regression/v1",
            "source": source, "expected_declaration": "wanted", "expected_proposition": "False",
            "outcome": outcome.to_dict(), "model_or_statutory_admission": False},
            sort_keys=True, indent=2)+"\n", encoding="utf-8")
    assert outcome.result.status is not ResultStatus.PROVED
    assert outcome.receipt.accepted is False


# Lexer-boundary controls only; no native compiler or legal-meaning claim.
@pytest.mark.parametrize(("label", "prefix"), [('quoted-double-quote', 'def «name"left» : Nat := 0'), ('quoted-comment-markers', 'def «-- /- axiom "» : Nat := 0'), ('quoted-first-close', 'def «outer«inner» : Nat := 0'), ('quoted-backslash-close', 'def «left\\» : Nat := 0'), ('character-guillemet', "def c : Char := '«'"), ('character-double-quote', 'def c : Char := \'"\''), ('character-escaped-quote', "def c : Char := '\\''"), ('character-hex', "def c : Char := '\\x22'"), ('primed-qualified', "def Name.prime' : Nat := 0"), ('unicode-primed', "def α₀' : Nat := 0"), ('ordinary-string', 'def text : String := "quotes: \\" and «"'), ('ordinary-gap', 'def text : String := "first\\\n  second"'), ('raw-zero-backslash', 'r"\\"'), ('raw-one-inner-quote', 'r#"inner " and \\"#'), ('raw-two-inner-hash', 'r##"inner "# and \\"##'), ('numeric-hex-adjacent-raw', '0xffr"\\"'), ('numeric-binary-adjacent-raw', '0b101r#"\\"#'), ('numeric-octal-adjacent-raw', '0o77r"\\"'), ('numeric-decimal-adjacent-raw', '12_3r"\\"'), ('numeric-scientific-adjacent-raw', '1.2e+3r#"\\"#')])
def test_lean_literal_boundaries_preserve_offsets_and_expose_following_policy_command(label, prefix):
    from ipfs_datasets_py.logic.backends.kernel import lean
    source = prefix + "\nset_option autoImplicit true\ntheorem wanted : True := by trivial\n"
    masked = lean._mask_lean_comments_and_strings(source)
    assert len(masked) == len(source)
    assert [i for i, char in enumerate(masked) if char == "\n"] == [i for i, char in enumerate(source) if char == "\n"]
    start = source.index("set_option autoImplicit true")
    assert masked[start:start + len("set_option autoImplicit true")] == "set_option autoImplicit true"
    assert "lean_source_contains_unsupported_metaprogramming_or_output" in lean.scan_lean_incomplete_or_unsafe(source)


@pytest.mark.parametrize(("label", "prefix"), [('quoted-danger-words', 'def «sorry admit axiom # set_option "» : Nat := 0'), ('character-hash', "def c : Char := '#'"), ('character-guillemet', "def c : Char := '«'"), ('character-unicode-escape', "def c : Char := '\\u00ab'"), ('ordinary-string', 'def text : String := "sorry admit axiom # set_option «"'), ('raw-zero', 'r"sorry admit axiom # set_option «"'), ('raw-one', 'r#"sorry " admit axiom # set_option \\"#'), ('raw-two', 'r##"sorry "# admit axiom # set_option \\"##'), ('nested-comments', '/- sorry /- admit " « -/ axiom # -/'), ('line-comment', '-- sorry admit axiom # " «')])
def test_lean_literal_contents_do_not_become_active_policy_commands(label, prefix):
    from ipfs_datasets_py.logic.backends.kernel import lean
    source = prefix + "\ntheorem wanted : True := by trivial\n"
    assert lean.scan_lean_incomplete_or_unsafe(source) == ()
    assert lean.extract_lean_theorem_name(source) == "wanted"


@pytest.mark.parametrize(("label", "source"), [('quoted-open', 'def «unterminated : Nat := 0'), ('raw-open', 'r#"unterminated"'), ('raw-hash-mismatch', 'r##"unterminated"#'), ('string-open', '"unterminated'), ('char-open', "'«"), ('char-too-long', "'ab'"), ('char-invalid-escape', "'\\q'"), ('char-short-hex', "'\\x2'"), ('number-incomplete', '0xff_'), ('scientific-incomplete', '1e+'), ('string-double-gap', '"first\\\n \n second"')])
def test_lean_incomplete_literal_boundaries_refuse_without_hiding_later_text(label, source):
    from ipfs_datasets_py.logic.backends.kernel import lean
    with pytest.raises(LeanKernelError):
        lean._mask_lean_comments_and_strings(source)


@pytest.mark.parametrize("aliases", [
    {"source": "theorem wanted : True := True.intro\n"},
    {"lean": "theorem wanted : True := True.intro\n"},
    {"checked_source": "theorem wanted : True := True.intro\n"},
    dict.fromkeys(("lean", "source", "checked_source"), "theorem wanted : True := True.intro\n"),
    {"lean": "", "source": "theorem wanted : True := True.intro\n", "checked_source": None},
])
def test_lean_source_aliases_bind_one_exact_source(aliases):
    from dataclasses import replace
    from ipfs_datasets_py.logic.backends.kernel import lean
    request = _request(family="lean4", encoding="lean4", source="unused")
    request = replace(request, payload=FrozenMap({"encoding": "lean4", **aliases}))
    source, encoding, translation = lean._payload_source(request)
    assert source == "theorem wanted : True := True.intro\n"
    assert encoding == "lean4" and translation is None


@pytest.mark.parametrize("pair", [
    ("lean", "source"), ("lean", "checked_source"), ("source", "checked_source"),
])
@pytest.mark.parametrize("other", [
    "theorem wanted : False := by sorry\n",
    "theorem wanted : True := True.intro\n\n",  # bytes, not stripped text
])
def test_lean_conflicting_source_aliases_reject_before_execution(pair, other):
    from dataclasses import replace
    aliases = {pair[0]: "theorem wanted : True := True.intro\n", pair[1]: other}
    request = _request(family="lean4", encoding="lean4", source="unused")
    request = replace(request, payload=FrozenMap({"encoding": "lean4", **aliases}))
    runner, calls = _process_runner("")
    backend = LeanKernelBackend(runner=runner,
        native_probe=lambda: pytest.fail("conflicting source reached capability probe"),
        native_identity_probe=lambda *args, **kwargs: pytest.fail("conflicting source reached native identity"))
    with pytest.raises(LeanKernelError, match="unambiguous checked Lean source"):
        backend.run(request)
    assert calls == []


@pytest.mark.parametrize("alias", ["lean", "source", "checked_source"])
@pytest.mark.parametrize("invalid", [False, 0, [], {}, 42, "   ", "bad\x00source"])
def test_lean_malformed_source_alias_cannot_hide_beside_valid_source(alias, invalid):
    from dataclasses import replace
    from ipfs_datasets_py.logic.backends.kernel import lean
    aliases = dict.fromkeys(("lean", "source", "checked_source"), "theorem wanted : True := True.intro\n")
    aliases[alias] = invalid
    request = _request(family="lean4", encoding="lean4", source="unused")
    request = replace(request, payload=FrozenMap({"encoding": "lean4", **aliases}))
    with pytest.raises(LeanKernelError, match="Lean source must be non-empty text"):
        lean._payload_source(request)


@pytest.mark.parametrize("token", [
    "s!", "m!", "f!", "dbg_trace", "trace", "throwNamedError", "throwNamedErrorAt",
    "logNamedError", "logNamedErrorAt", "logNamedWarning", "logNamedWarningAt",
    "throwError", "throwErrorAt",
])
@pytest.mark.parametrize("gap", ["", " ", "/- literal boundary -/\n"])
def test_lean_interpolating_tokens_fail_explicitly_instead_of_hiding_terms(token, gap):
    """Lexical profile coverage only, not compilation of every token combination."""
    source = 'def value := ' + token + gap + '"{(by sorry : Nat)}"\ntheorem wanted : True := True.intro\n'
    with pytest.raises(LeanKernelError, match="interpolated Lean syntax is unsupported"):
        scan_lean_incomplete_or_unsafe(source)


@pytest.mark.parametrize("body", ["sorry", "admit", "run_tac pure (); exact 7"])
def test_lean_interpolated_proof_terms_never_reach_compiler(body):
    source = 'def value : String := s!"{(by ' + body + ' : Nat)}"\ntheorem wanted : True := True.intro\n'
    runner, calls = _process_runner("")
    backend = LeanKernelBackend(runner=runner,
        native_probe=lambda: _available_native("lean", "fixture-not-an-executed-compiler"),
        native_identity_probe=lambda *args, **kwargs: pytest.fail("interpolation reached native identity"))
    with pytest.raises(LeanKernelError, match="interpolated Lean syntax is unsupported"):
        backend.run(_request(family="lean4", encoding="lean4", source=source,
            expected_declaration="wanted", expected_proposition="True"))
    assert calls == []


def test_lean_interpolated_expected_proposition_is_not_a_complete_literal():
    from ipfs_datasets_py.logic.backends.kernel import lean
    with pytest.raises(LeanKernelError, match="interpolated Lean syntax is unsupported"):
        lean._expected_proposition('s!"{(by sorry : Nat)}" = ""')


@pytest.mark.parametrize("prefix", [
    'def value := NS.s! "literal {sorry}"',
    'def value := s!name "literal {admit}"',
    'def value := s!\' "literal {run_tac}"',
    'def value := αs! "literal {sorry}"',
    'def value := «s!» "literal {sorry}"',
    'def value := `s!',
    'def value := `dbg_trace',
    'def value := NS.throwError "literal {sorry}"',
    'def value := traceMore "literal {sorry}"',
    'def value := "s! m! f! dbg_trace trace throwError {sorry}"',
    'def value := r#"s!\"{sorry}\" dbg_trace"#',
    '/- s!"{sorry}" /- dbg_trace -/ throwError -/',
    '-- s!"{sorry}" throwError',
])
def test_lean_interpolation_policy_preserves_noninterpolating_token_contexts(prefix):
    assert scan_lean_incomplete_or_unsafe(prefix + "\ntheorem wanted : True := True.intro\n") == ()


def test_native_cache_fixture_loader_uses_pinned_current_owner_without_invoking_helpers():
    import sys
    fixture_path = Path(__file__).resolve().parents[3] / "unit/logic/legal_ir/test_proof_cache.py"
    prior = sys.getprofile()
    called = []
    def watch(frame, event, argument):
        if event == "call" and frame.f_code.co_filename == str(fixture_path):
            # Module/class definitions are declarations. No authored fixture,
            # test, kernel, native identity or constructor function may run.
            assert frame.f_code.co_name in {"<module>", "_ShadowObservation"}
            called.append(frame.f_code.co_name)
    try:
        sys.setprofile(watch)
        owner = _load_native_proof_cache_fixture_owner()
    finally:
        sys.setprofile(prior)
    assert called and "<module>" in called
    assert owner.__name__ == "_native_lean_cache_fixture_owner"
    assert owner.__file__ == owner.__spec__.origin == str(fixture_path)
    assert owner._legal_artifact.__code__.co_filename == str(fixture_path)
    assert owner._reviewed_fixture.__code__.co_filename == str(fixture_path)


def test_native_cache_fixture_loader_refuses_tampered_preimage_before_module_creation(monkeypatch):
    import importlib.util
    fixture_path = Path(__file__).resolve().parents[3] / "unit/logic/legal_ir/test_proof_cache.py"
    original_read = Path.read_bytes
    def changed(path):
        raw = original_read(path)
        return raw + b"\n# fictional pre-import drift\n" if path == fixture_path else raw
    monkeypatch.setattr(Path, "read_bytes", changed)
    monkeypatch.setattr(importlib.util, "spec_from_file_location",
                        lambda *a, **k: pytest.fail("tampered fixture reached module construction"))
    with pytest.raises(AssertionError, match="source pin differs before import"):
        _load_native_proof_cache_fixture_owner()


def test_native_cache_fixture_loader_refuses_post_import_drift_without_retry(monkeypatch):
    fixture_path = Path(__file__).resolve().parents[3] / "unit/logic/legal_ir/test_proof_cache.py"
    original_read = Path.read_bytes
    reads = []
    def changed(path):
        raw = original_read(path)
        if path == fixture_path:
            reads.append(path)
            if len(reads) > 1:
                return raw + b"\n# fictional post-import drift\n"
        return raw
    monkeypatch.setattr(Path, "read_bytes", changed)
    with pytest.raises(AssertionError, match="source changed during import"):
        _load_native_proof_cache_fixture_owner()
    assert len(reads) == 2


# Deliberately authored compiler-stream fixtures only; no Lean process runs.
def _bound_clean_lean_dependency_fixture():
    from ipfs_datasets_py.logic.backends.kernel import lean
    source = "theorem wanted : True := by trivial\n"
    instrumented = lean.instrument_lean_source_for_axioms(source, "wanted", expected_proposition="True")
    guard = lean.lean_expected_obligation_declaration(source, "wanted", "True")
    line = instrumented[:instrumented.rfind("#print axioms")].count("\n") + 1
    stdout = _axiom_message("'" + guard + "' does not depend on any axioms",
        fileName="Main.lean", pos={"line": line, "column": 0})
    return stdout, {"declaration": guard, "expected_source_path": "Main.lean", "expected_source_line": line}


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
@pytest.mark.parametrize("diagnostic", [
    json.dumps({"severity": "error", "data": "fictional unsolved goals"}) + "\n",
    "  " + json.dumps({"severity": "error", "data": "fictional type mismatch"}) + "\n",
    "error: fictional unsolved goals\n",
    "Main.lean:1:0: error: fictional unsolved goals\n",
    "  \tMain.lean:12:3: error: fictional unsolved goals\n",
    "  ERROR: fictional unsolved goals\n",
])
def test_lean_bound_error_diagnostics_on_either_stream_cannot_be_rescued(stream, diagnostic):
    stdout, expected = _bound_clean_lean_dependency_fixture()
    process = _lean_output(stdout + (diagnostic if stream == "stdout" else ""),
        stderr=diagnostic if stream == "stderr" else "")
    accepted, report, diagnostics = evaluate_lean_kernel_output(process, **expected)
    assert accepted is False
    assert report is None  # Error diagnostics never become elaborated axiom evidence.
    assert any("reported error diagnostics" in message for message in diagnostics)


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
@pytest.mark.parametrize("diagnostic", [
    '{"severity":"error","severity":"warning","data":"fictional failure"}',
    '{"severity":"warning","data":"first","data":"second"}',
    '{"severity":"warning","data":NaN}',
    '{"severity":"error","data":"unfinished"',
    '[{"severity":"error","data":"fictional failure"}]',
])
def test_lean_bound_ambiguous_or_malformed_json_diagnostics_fail_closed(stream, diagnostic):
    stdout, expected = _bound_clean_lean_dependency_fixture()
    process = _lean_output(stdout + (diagnostic if stream == "stdout" else ""),
        stderr=diagnostic if stream == "stderr" else "")
    accepted, _, diagnostics = evaluate_lean_kernel_output(process, **expected)
    assert accepted is False
    assert diagnostics


@pytest.mark.parametrize("stderr", [
    "warning: a fictional warning mentions the word error without failing\n",
    "  Main.lean:2:0: warning: the text error: is only an example\n",
    json.dumps({"severity": "warning", "data": "Main.lean:2:0: error: quoted diagnostic example"}),
    json.dumps({"severity": "information", "data": "error: is quoted diagnostic text"}),
    "  \t\n",
])
def test_lean_bound_harmless_stderr_warnings_preserve_dependency_evidence(stderr):
    stdout, expected = _bound_clean_lean_dependency_fixture()
    accepted, report, diagnostics = evaluate_lean_kernel_output(_lean_output(stdout, stderr=stderr), **expected)
    assert accepted is True
    assert report is not None and report.declaration == expected["declaration"]
    assert report.source_path == expected["expected_source_path"]
    assert report.source_line == expected["expected_source_line"]
    assert diagnostics == ()


@pytest.mark.parametrize("severity", ["warning", "information"])
def test_lean_bound_stdout_json_warning_may_quote_error_text(severity):
    stdout, expected = _bound_clean_lean_dependency_fixture()
    warning = json.dumps({"severity": severity, "data": "Main.lean:1:0: error: is quoted text"}) + "\n"
    accepted, report, diagnostics = evaluate_lean_kernel_output(_lean_output(stdout + warning), **expected)
    assert accepted is True and report is not None and diagnostics == ()


@pytest.mark.parametrize("damage", ["stderr_report", "duplicate_stdout_report", "wrong_declaration", "wrong_source_line"])
def test_lean_error_stream_policy_preserves_strict_dependency_report_binding(damage):
    stdout, expected = _bound_clean_lean_dependency_fixture()
    stderr = ""
    if damage == "stderr_report": stderr = stdout
    elif damage == "duplicate_stdout_report": stdout += stdout
    elif damage == "wrong_declaration": expected["declaration"] = "another_requested_declaration"
    else: expected["expected_source_line"] += 1
    accepted, _, _ = evaluate_lean_kernel_output(_lean_output(stdout, stderr=stderr), **expected)
    assert accepted is False


def test_lean_json_diagnostic_reader_remains_a_graceful_collector():
    from ipfs_datasets_py.logic.backends.kernel import lean
    warning = {"severity": "warning", "data": "an error word in harmless text"}
    valid = json.dumps(warning) + "\n"
    damaged = 'not JSON\n[]\n{"severity":"warning","data":NaN}\n' + '{"severity":"error","severity":"warning"}\n'
    assert lean.parse_lean_json_messages(damaged + valid) == [warning]
    assert lean.parse_lean_json_messages(None) == []


def test_lean_fresh_backend_receipt_explicitly_binds_current_verification_profile():
    from ipfs_datasets_py.logic.backends.kernel import lean
    outcome, calls, _ = _bound_lean_outcome()
    assert calls and outcome.receipt.accepted is True
    assert outcome.receipt.schema_version == "lean-kernel-receipt/v3"
    assert outcome.receipt.toolchain.metadata["verification_profile"] == lean.LEAN_KERNEL_VERIFICATION_PROFILE
    assert LeanKernelReceipt.from_dict(outcome.receipt.to_dict()).to_dict() == outcome.receipt.to_dict()


@pytest.mark.parametrize("profile", [None, "lean-kernel-verification/v0", True, {}, [], 1, "lean-kernel-verification/v1"])
def test_lean_old_or_wrong_verification_profile_cannot_be_reissued_as_current(profile):
    outcome, _, _ = _bound_lean_outcome()
    value = copy.deepcopy(outcome.receipt.to_dict())
    if profile is None:
        value["toolchain"]["metadata"].pop("verification_profile")
    else:
        value["toolchain"]["metadata"]["verification_profile"] = profile
    # Reach the actual generation gate, not an unrelated stale receipt ID.
    value["receipt_id"] = "lean-kernel-receipt:" + stable_digest({key: item for key, item in value.items() if key != "receipt_id"})
    preserved = copy.deepcopy(value)
    with pytest.raises(LeanKernelError, match="current explicit verification profile"):
        LeanKernelReceipt.from_dict(value)
    assert value == preserved  # No inferred token or in-place archival upgrade.


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
@pytest.mark.parametrize("diagnostic", [
    json.dumps({"severity": "error", "data": "fictional BOM unsolved goals"}) + "\n",
    "error: fictional BOM unsolved goals\n",
    "  Main.lean:1:0: error: fictional BOM unsolved goals\n",
])
def test_lean_framing_bom_cannot_hide_error_diagnostics(stream, diagnostic):
    stdout, expected = _bound_clean_lean_dependency_fixture()
    if stream == "stdout": stdout = "\ufeff" + diagnostic + stdout
    stderr = "\ufeff" + diagnostic if stream == "stderr" else ""
    accepted, report, diagnostics = evaluate_lean_kernel_output(_lean_output(stdout, stderr=stderr), **expected)
    assert accepted is False and report is None
    assert any("reported error diagnostics" in message for message in diagnostics)


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_lean_one_stream_bom_preserves_json_warning_quoting_error(stream):
    stdout, expected = _bound_clean_lean_dependency_fixture()
    warning = "\ufeff" + json.dumps({"severity": "warning", "data": "error: is quoted warning text"}) + "\n"
    if stream == "stdout": stdout = warning + stdout
    stderr = warning if stream == "stderr" else ""
    accepted, report, diagnostics = evaluate_lean_kernel_output(_lean_output(stdout, stderr=stderr), **expected)
    assert accepted is True and report is not None and diagnostics == ()


def test_lean_one_stderr_bom_preserves_plain_warning_and_empty_stream():
    stdout, expected = _bound_clean_lean_dependency_fixture()
    for stderr in ("\ufeffwarning: the word error does not make this a failure\n", "\ufeff"):
        accepted, report, diagnostics = evaluate_lean_kernel_output(_lean_output(stdout, stderr=stderr), **expected)
        assert accepted is True and report is not None and diagnostics == ()


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
@pytest.mark.parametrize("diagnostic", [
    "\ufeff\ufeff" + json.dumps({"severity": "error", "data": "extra BOM"}) + "\n",
    json.dumps({"severity": "warning", "data": "ordinary warning"}) + "\n\ufefferror: misplaced BOM\n",
])
def test_lean_additional_or_misplaced_diagnostic_bom_fails_closed(stream, diagnostic):
    stdout, expected = _bound_clean_lean_dependency_fixture()
    if stream == "stdout": stdout = diagnostic + stdout
    stderr = diagnostic if stream == "stderr" else ""
    accepted, _, diagnostics = evaluate_lean_kernel_output(_lean_output(stdout, stderr=stderr), **expected)
    assert accepted is False and diagnostics


def test_lean_one_output_bom_preserves_the_single_bound_dependency_report():
    stdout, expected = _bound_clean_lean_dependency_fixture()
    accepted, report, diagnostics = evaluate_lean_kernel_output(_lean_output("\ufeff" + stdout), **expected)
    assert accepted is True and report is not None and diagnostics == ()


# Source-policy admission controls only; no native execution or proof-soundness claim.
_LEAN_EVALUATION_SOURCE_POLICY_CASES = [
    "run_elab pure ()\ntheorem wanted : True := True.intro\n",
    "run_meta pure ()\ntheorem wanted : True := True.intro\n",
    "theorem wanted : True := by_elab pure (Lean.mkConst ``True.intro)\n",
]


@pytest.mark.parametrize("source", _LEAN_EVALUATION_SOURCE_POLICY_CASES,
                         ids=["run-elab", "run-meta", "by-elab"])
def test_lean_evaluation_metaprograms_are_rejected_by_source_policy(source):
    assert "lean_source_contains_unsupported_metaprogramming_or_output" in scan_lean_incomplete_or_unsafe(source)


@pytest.mark.parametrize("source", _LEAN_EVALUATION_SOURCE_POLICY_CASES,
                         ids=["run-elab", "run-meta", "by-elab"])
def test_lean_evaluation_metaprograms_never_reach_identity_or_runner(source):
    runner_calls, identity_calls = [], []

    def execute(invocation, _cancellation):
        runner_calls.append(invocation)
        raise AssertionError("unsupported evaluation source reached runner tripwire")

    def observe():
        identity_calls.append(True)
        return _fictional_native_identity()

    backend = LeanKernelBackend(runner=BoundedToolRunner(executor=execute),
        native_probe=lambda: _available_native("lean", "fixture-not-an-executed-compiler"),
        native_identity_probe=observe)
    outcome = backend.run(_request(family="lean4", encoding="lean4", source=source,
        expected_declaration="wanted", expected_proposition="True"))
    assert outcome.result.status is ResultStatus.MALFORMED
    assert outcome.receipt.accepted is False
    assert "lean_source_contains_unsupported_metaprogramming_or_output" in outcome.receipt.diagnostics
    assert runner_calls == [] and identity_calls == []


@pytest.mark.parametrize("prefix", [
    "",
    "-- run_elab pure (); run_meta pure (); by_elab pure (Lean.mkConst ``True.intro)\n"
    "/- run_elab run_meta by_elab -/\n",
    'def words : String := "run_elab run_meta by_elab"\n',
], ids=["clean-theorem", "comments-only", "string-only"])
def test_lean_evaluation_metaprogram_words_remain_inert_in_comments_and_strings(prefix):
    source = prefix + "theorem wanted : True := True.intro\n"
    assert scan_lean_incomplete_or_unsafe(source) == ()



def test_native_cache_fixture_loader_supplies_canonical_constructor_contract_without_execution():
    """The Native caller needs current fixture constructors, never a compiler run."""
    import inspect
    import sys

    fixture_path = Path(__file__).resolve().parents[3] / "unit/logic/legal_ir/test_proof_cache.py"
    prior = sys.getprofile()
    calls = []

    def constructors_not_called(frame, event, argument):
        if event == "call" and frame.f_code.co_filename == str(fixture_path):
            # Bind the exact Native caller's constructor arguments below, but
            # do not invoke fixture, adapter/compiler, kernel or model helpers.
            assert frame.f_code.co_name not in {"_reviewed_fixture", "_legal_artifact"}
            calls.append(frame.f_code.co_name)

    try:
        sys.setprofile(constructors_not_called)
        owner = _load_native_proof_cache_fixture_owner()
        fixture_arguments = {
            "sample_id": "fictional-native-cache-provision",
            "citation": "FICTIONAL Test Act 1",
            "section": "1",
            "text": "A fictional agency shall publish a fictional notice.",
        }
        assert inspect.signature(owner._reviewed_fixture).bind(**fixture_arguments).arguments == fixture_arguments
        sample_marker = object()
        assert inspect.signature(owner._legal_artifact).bind(sample_marker).arguments == {"sample": sample_marker}
        assert owner._reviewed_fixture.__globals__ is owner.__dict__
        assert owner._legal_artifact.__globals__ is owner.__dict__
        assert owner.LegalSample is sys.modules[
            "ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples"
        ].LegalSample
        assert owner.FormalizationArtifact is sys.modules[
            "ipfs_datasets_py.logic.formalization.compiler"
        ].FormalizationArtifact
        assert owner.LegalIRFormalizationAdapter is sys.modules[
            "ipfs_datasets_py.logic.legal_ir.adapter"
        ].LegalIRFormalizationAdapter
    finally:
        sys.setprofile(prior)
    assert "<module>" in calls
    assert owner._reviewed_fixture.__code__.co_filename == str(fixture_path)
    assert owner._legal_artifact.__code__.co_filename == str(fixture_path)


@pytest.mark.parametrize("mutation", [
    "different-result", "different-source", "contradictory-status",
    "different-witness-receipt", "different-witness-theorem", "different-capability",
])
def test_lean_outcome_rejects_inconsistent_evidence(mutation):
    from dataclasses import replace

    outcome, _, request = _bound_lean_outcome()
    assert outcome.result.status is ResultStatus.PROVED and outcome.receipt.accepted
    assert replace(outcome).to_dict() == outcome.to_dict()
    different, _, different_request = _bound_lean_outcome(
        source="theorem another : True := by trivial\n", name="another")
    assert different.receipt.accepted and request.digest != different_request.digest

    if mutation == "different-result":
        changes = {"result": different.result}
    elif mutation == "different-source":
        changes = {"source_binding": replace(
            outcome.source_binding, source_digest=different.source_binding.source_digest)}
    elif mutation == "contradictory-status":
        changes = {"result": replace(outcome.result, status=ResultStatus.ERROR, reason="fixture error")}
    elif mutation == "different-capability":
        changes = {"capability": replace(
            outcome.capability, native=KernelCapabilityState.unavailable(
                plane=CapabilityPlane.NATIVE, kernel_id="lean", reason="fixture difference"))}
    else:
        key = "receipt_id" if mutation == "different-witness-receipt" else "theorem_digest"
        witness = outcome.result.witness.to_dict()
        witness[key] = different.result.witness[key]
        changes = {"result": replace(outcome.result, witness=witness)}
    with pytest.raises(LeanKernelError, match="outcome (?:source|result|status)"):
        replace(outcome, **changes)


@pytest.mark.parametrize("field", ["result_id", "assumptions", "bounds"])
def test_lean_outcome_rejects_fields_from_another_request(field):
    from dataclasses import replace

    outcome, calls, request = _bound_lean_outcome()
    fresh, _, second_request = _bound_lean_outcome(
        source="theorem another : True := by trivial\n", name="another")
    assert calls and request.digest != second_request.digest
    assert outcome.receipt.accepted and fresh.receipt.accepted
    assert outcome.result.assumptions == request.assumption_ids
    assert outcome.result.bounds == request.bounds
    if field == "result_id":
        value = fresh.result.result_id
    elif field == "assumptions":
        value = (*request.assumption_ids, "assumption:other-fixture")
    else:
        value = replace(request.bounds, max_steps=request.bounds.max_steps + 1)
    changed = replace(outcome.result, **{field: value})
    assert getattr(changed, field) != getattr(outcome.result, field)
    assert changed.metadata == outcome.result.metadata and changed.witness == outcome.result.witness
    with pytest.raises(LeanKernelError, match="outcome result .*request"):
        replace(outcome, result=changed)
