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
