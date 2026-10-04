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

import pytest
from ipfs_datasets_py.logic.backends.kernel.lean import (
    LEAN_KERNEL_BACKEND_VERSION,
    LeanAuthorityDisposition,
    LeanKernelBackend,
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
) -> BackendRequest:
    payload: dict = {"encoding": encoding, "source": source}
    if translation is not None:
        payload["translation"] = translation
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


def _process_runner(
    stdout: str,
    *,
    returncode: int | None = 0,
    timed_out: bool = False,
    unavailable: bool = False,
    output_truncated: bool = False,
    expected_suffix: str = "",
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
        return RawProcessResult(
            returncode=returncode,
            stdout=stdout,
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
        expected_suffix="#print axioms and_comm",
    )
    backend = LeanKernelBackend(
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
    assert outcome.receipt.toolchain.executable == "lean"
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
    backend = LeanKernelBackend(
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
    backend = LeanKernelBackend(
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
    backend = LeanKernelBackend(
        native_probe=lambda: _available_native("lean", "lean"),
    )
    outcome = backend.run(
        _request(family="lean4", encoding="lean4", source=LEAN_UNSAFE)
    )
    assert outcome.result.status is ResultStatus.MALFORMED
    assert "lean_source_contains_unsafe_or_unreviewed_axiom" in outcome.receipt.diagnostics
    assert outcome.receipt.accepted is False


def test_unavailable_lean_kernel_never_passes():
    backend = LeanKernelBackend(
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
    backend = LeanKernelBackend(
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
    backend = LeanKernelBackend(
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
    assert LeanKernelBackend().interface_version == LEAN_KERNEL_BACKEND_VERSION
    assert RocqKernelBackend().interface_version == ROCQ_KERNEL_BACKEND_VERSION
