"""Integration contract for canonical Hammer + Isabelle kernel backends.

Covers LFV-G050 / LFV-032 acceptance:

* premise selection, SMT/ATP search, proof candidates, reconstruction, and
  kernel receipts are separate stages;
* provider sets are registry driven;
* unreconstructed success is candidate only;
* Isabelle ``sorry`` and unreviewed axiomatization reject or explicitly
  downgrade authority;
* Isabelle path metadata is corrected (theory header drives ``.thy`` path).
"""

from __future__ import annotations

import pytest
from ipfs_datasets_py.logic.backends.kernel.isabelle import (
    ISABELLE_KERNEL_BACKEND_VERSION,
    IsabelleAuthorityDisposition,
    IsabelleKernelBackend,
    correct_isabelle_path_metadata,
    extract_isabelle_theory_name,
    scan_isabelle_incomplete_or_unreviewed,
)
from ipfs_datasets_py.logic.backends.kernel.wasm import (
    CapabilityPlane,
    KernelCapabilityState,
    WasmCapabilityProbe,
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
from ipfs_datasets_py.logic.hammers.backend import (
    HAMMER_BACKEND_VERSION,
    HammerBackend,
    HammerBackendError,
    HammerSearchCandidate,
    HammerStage,
    HammerStageStatus,
)
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap, stable_digest
from ipfs_datasets_py.logic.ir_core.protocols import (
    BackendRequest,
    ExecutionBounds,
    QueryKind,
)

ISABELLE_OK = """\
theory AndComm
  imports Main
begin

theorem and_comm: "P \\<and> Q \\<longrightarrow> Q \\<and> P"
  by auto

end
"""

ISABELLE_SORRY = """\
theory Incomplete
  imports Main
begin

theorem incomplete: "n = (n::nat)"
  sorry

end
"""

ISABELLE_AXIOM = """\
theory Unreviewed
  imports Main
begin

axiomatization evil where evil_ax: "False"

theorem still_there: "True"
  by auto

end
"""


def _request(
    *,
    family: str,
    encoding: str,
    source: str,
    backend_id: str = "",
    path: str = "",
    translation: dict | None = None,
    bounds: ExecutionBounds | None = None,
    extra_payload: dict | None = None,
) -> BackendRequest:
    payload: dict = {"encoding": encoding, "source": source}
    if path:
        payload["path"] = path
        payload["file_name"] = path
    if translation is not None:
        payload["translation"] = translation
    if extra_payload:
        payload.update(extra_payload)
    return BackendRequest(
        request_id="request:hammer:test",
        claim_id="claim:hammer:test",
        declaration_id="declaration:hammer:test",
        claim_digest="1" * 64,
        obligation_id="obligation:hammer:test",
        obligation_digest="2" * 64,
        assumption_ids=("assumption:reviewed",),
        logic_family=family,
        query_kind=QueryKind.THEOREM_PROOF,
        bounds=bounds or ExecutionBounds(timeout_ms=250, max_steps=20),
        payload=FrozenMap(payload),
        requested_backend_id=backend_id,
    )


def _translation(target_family: str = "isabelle") -> dict:
    return {
        "translation_id": "translation:isabelle:test",
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
    expected_theory: str = "",
) -> tuple[BoundedToolRunner, list[object]]:
    invocations: list[object] = []

    def execute(invocation, _cancellation):
        invocations.append(invocation)
        if expected_theory:
            # Corrected path: argv must use -T <theory> -d <session>, and the
            # theory file written into the private workspace must match.
            argv = list(invocation.argv)
            assert "process" in argv
            t_idx = argv.index("-T")
            assert argv[t_idx + 1] == expected_theory
            assert "-d" in argv
            theory_path = invocation.cwd / f"{expected_theory}.thy"
            assert theory_path.is_file(), (
                f"expected corrected theory file at {theory_path}; "
                f"workspace contents={[p.name for p in invocation.cwd.iterdir()]}"
            )
        return RawProcessResult(
            returncode=returncode,
            stdout=stdout,
            elapsed_seconds=0.011,
            timed_out=timed_out,
            process_tree_terminated=timed_out,
            error="executable not found" if unavailable else "",
        )

    return BoundedToolRunner(executor=execute), invocations


def _available_native(kernel_id: str = "isabelle", executable: str = "isabelle"):
    return KernelCapabilityState.available_native(
        kernel_id=kernel_id,
        executable=executable,
        version="test",
    )


# ---------------------------------------------------------------------------
# Isabelle path metadata correction
# ---------------------------------------------------------------------------


def test_isabelle_path_metadata_is_corrected_from_theory_header():
    meta = correct_isabelle_path_metadata(
        ISABELLE_OK, caller_path="Goal.thy", session_dir="."
    )
    assert meta.theory_name == "AndComm"
    assert meta.theory_path == "AndComm.thy"
    assert meta.caller_path == "Goal.thy"
    assert meta.corrected is True
    assert "{theory_name}" in meta.command_template
    assert extract_isabelle_theory_name(ISABELLE_OK) == "AndComm"


def test_isabelle_path_metadata_marks_matching_caller_path_uncorrected():
    meta = correct_isabelle_path_metadata(
        ISABELLE_OK, caller_path="AndComm.thy", session_dir="/tmp/session"
    )
    assert meta.corrected is False
    assert meta.theory_path == "AndComm.thy"
    assert meta.session_dir == "/tmp/session"


def test_isabelle_verified_proof_binds_corrected_path_and_receipt():
    runner, invocations = _process_runner(
        "val it = (): unit\n",
        expected_theory="AndComm",
    )
    backend = IsabelleKernelBackend(
        runner=runner,
        backend_version="2025",
        native_probe=lambda: _available_native(),
        wasm_probe=WasmCapabilityProbe(),
    )
    request = _request(
        family="isabelle",
        encoding="isabelle",
        source=ISABELLE_OK,
        backend_id="isabelle",
        path="Goal.thy",  # deliberately wrong; must be corrected
        translation=_translation(),
    )

    outcome = backend.run(request)

    assert outcome.interface_version == ISABELLE_KERNEL_BACKEND_VERSION
    assert isinstance(outcome.result, TheoremResult)
    assert outcome.result.status is ResultStatus.PROVED
    assert outcome.result.authority is ResultAuthority.THEOREM
    assert outcome.receipt.accepted is True
    assert outcome.receipt.theorem_name == "and_comm"
    assert outcome.receipt.imports == ("Main",)
    assert outcome.receipt.path_metadata.theory_path == "AndComm.thy"
    assert outcome.receipt.path_metadata.corrected is True
    assert outcome.receipt.source_tree.primary_path == "AndComm.thy"
    assert "AndComm.thy" in outcome.receipt.source_tree.files
    assert outcome.receipt.toolchain.command_template
    assert outcome.receipt.translation is not None
    assert outcome.result.witness["path_metadata"]["theory_path"] == "AndComm.thy"
    assert any("path metadata corrected" in d for d in outcome.receipt.diagnostics)
    assert invocations, "isabelle runner should have been invoked"
    assert outcome.capability.wasm_available is False
    # Isabelle WASM is outside the reviewed support set (lean4/rocq only today)
    # and is reported as a distinct non-available plane, never collapsed into
    # native success.
    assert outcome.capability.wasm.available is False
    assert outcome.capability.wasm.plane is CapabilityPlane.WASM


def test_isabelle_sorry_is_rejected_and_never_proved():
    backend = IsabelleKernelBackend(
        native_probe=lambda: _available_native(),
    )
    outcome = backend.run(
        _request(
            family="isabelle",
            encoding="isabelle",
            source=ISABELLE_SORRY,
            path="Incomplete.thy",
        )
    )
    assert outcome.result.status is ResultStatus.MALFORMED
    assert outcome.receipt.accepted is False
    assert "isabelle_source_contains_sorry_or_oops" in outcome.receipt.diagnostics
    assert outcome.result.status is not ResultStatus.PROVED
    assert "isabelle_source_contains_sorry_or_oops" in scan_isabelle_incomplete_or_unreviewed(
        ISABELLE_SORRY
    )


def test_isabelle_sorry_can_explicitly_downgrade_authority():
    backend = IsabelleKernelBackend(
        incomplete_disposition=IsabelleAuthorityDisposition.DOWNGRADE,
        native_probe=lambda: _available_native(),
    )
    outcome = backend.run(
        _request(family="isabelle", encoding="isabelle", source=ISABELLE_SORRY)
    )
    assert isinstance(outcome.result, CandidateResult)
    assert outcome.result.authority is ResultAuthority.CANDIDATE
    assert outcome.result.status is ResultStatus.CANDIDATE
    assert (
        outcome.result.witness["candidate_kind"]
        == "incomplete_or_unreviewed_isabelle_proof"
    )
    assert (
        outcome.receipt.authority_disposition is IsabelleAuthorityDisposition.DOWNGRADE
    )
    assert outcome.receipt.accepted is False


def test_isabelle_unreviewed_axiomatization_is_rejected():
    backend = IsabelleKernelBackend(
        native_probe=lambda: _available_native(),
    )
    outcome = backend.run(
        _request(family="isabelle", encoding="isabelle", source=ISABELLE_AXIOM)
    )
    assert outcome.result.status is ResultStatus.MALFORMED
    assert (
        "isabelle_source_contains_unreviewed_axiomatization"
        in outcome.receipt.diagnostics
    )
    assert outcome.receipt.accepted is False


def test_unavailable_isabelle_kernel_never_passes():
    backend = IsabelleKernelBackend(
        native_probe=lambda: KernelCapabilityState.unavailable(
            plane=CapabilityPlane.NATIVE,
            kernel_id="isabelle",
            reason="isabelle executable not found on PATH",
            executable="isabelle",
        ),
        wasm_probe=WasmCapabilityProbe(),
    )
    outcome = backend.run(
        _request(family="isabelle", encoding="isabelle", source=ISABELLE_OK)
    )
    assert outcome.result.status is ResultStatus.UNAVAILABLE
    assert outcome.receipt.accepted is False
    assert outcome.result.status is not ResultStatus.PROVED
    # Path metadata still corrected even when unavailable.
    assert outcome.receipt.path_metadata.theory_path == "AndComm.thy"


# ---------------------------------------------------------------------------
# HammerBackend stages and registry
# ---------------------------------------------------------------------------


def test_hammer_stages_are_separate_and_registry_driven():
    def proved_solver(*, translation, premises, bounds):
        return {
            "verdict": "proved",
            "stdout": "(proof found)",
            "premise_ids": [p.premise_id for p in premises],
        }

    hammer = HammerBackend(
        solver_providers=[],
        reconstructor_providers=[],
    )
    hammer.register_solver_id("z3", available=True, runner=proved_solver)
    hammer.register_solver_id("cvc5", available=False)
    hammer.register_reconstructor_id("isabelle", available=False)

    registry = hammer.provider_registry()
    assert "z3" in registry.solver_ids()
    assert "cvc5" in registry.solver_ids()
    assert "isabelle" in registry.reconstructor_ids()
    assert registry.to_dict()["schema_version"]

    candidates, search_receipt, candidate_receipt = hammer.search_candidates(
        provider_ids=("z3", "cvc5"),
    )
    assert len(candidates) == 1
    assert candidates[0].verdict == "proved"
    assert candidates[0].reconstructed is False
    assert search_receipt.stage is HammerStage.SMT_ATP_SEARCH
    assert search_receipt.status is HammerStageStatus.CANDIDATE_ONLY
    assert search_receipt.authority is ResultAuthority.CANDIDATE
    assert candidate_receipt.stage is HammerStage.PROOF_CANDIDATES
    assert candidate_receipt.authority is ResultAuthority.CANDIDATE
    assert candidate_receipt.payload["theorem_authority_forbidden"] is True
    assert candidate_receipt.payload["unreconstructed"] is True


def test_unreconstructed_solver_success_is_candidate_only():
    def proved_solver(*, translation, premises, bounds):
        return {"verdict": "proved", "stdout": "SZS status Theorem"}

    hammer = HammerBackend(solver_providers=[], reconstructor_providers=[])
    hammer.register_solver_id("vampire", available=True, runner=proved_solver)

    outcome = hammer.run(
        _request(
            family="hammer",
            encoding="smtlib",
            source="(assert true)",
            backend_id="hammer",
            extra_payload={
                "goal_statement": "P -> P",
                "solver_providers": ["vampire"],
                "itp": "lean",
            },
        ),
        stages=(
            HammerStage.SMT_ATP_SEARCH,
            HammerStage.PROOF_CANDIDATES,
            HammerStage.RECONSTRUCTION,
        ),
    )

    assert outcome.interface_version == HAMMER_BACKEND_VERSION
    assert isinstance(outcome.result, CandidateResult)
    assert outcome.result.authority is ResultAuthority.CANDIDATE
    assert outcome.result.status is ResultStatus.CANDIDATE
    assert outcome.result.witness["candidate_kind"] == "unreconstructed_solver_success"
    assert outcome.result.witness["theorem_authority_forbidden"] is True
    assert outcome.stage(HammerStage.SMT_ATP_SEARCH) is not None
    assert outcome.stage(HammerStage.PROOF_CANDIDATES) is not None
    assert outcome.stage(HammerStage.RECONSTRUCTION) is not None
    # Must not silently claim theorem proof from solver alone.
    assert not isinstance(outcome.result, TheoremResult)
    assert all(c.reconstructed is False for c in outcome.candidates)


def test_hammer_search_candidate_forbids_reconstructed_flag():
    with pytest.raises(HammerBackendError):
        HammerSearchCandidate(
            candidate_id="c1",
            provider_id="z3",
            verdict="proved",
            reconstructed=True,
        )


def test_hammer_with_isabelle_kernel_verifies_via_kernel_receipt_stage():
    runner, invocations = _process_runner(
        "val it = (): unit\n",
        expected_theory="AndComm",
    )
    kernel = IsabelleKernelBackend(
        runner=runner,
        native_probe=lambda: _available_native(),
        wasm_probe=WasmCapabilityProbe(),
    )
    hammer = HammerBackend(
        solver_providers=[],
        reconstructor_providers=[],
        isabelle_kernel=kernel,
    )

    # No solver success — kernel path alone can prove when accepted.
    outcome = hammer.run(
        _request(
            family="hammer",
            encoding="isabelle",
            source=ISABELLE_OK,
            backend_id="hammer",
            path="Goal.thy",
            translation=_translation(),
            extra_payload={"itp": "isabelle", "native_source": ISABELLE_OK},
        ),
        stages=(HammerStage.KERNEL_RECEIPTS,),
    )

    assert outcome.kernel_outcome is not None
    assert outcome.kernel_outcome.receipt.accepted is True
    assert outcome.kernel_outcome.receipt.path_metadata.theory_path == "AndComm.thy"
    assert isinstance(outcome.result, TheoremResult)
    assert outcome.result.status is ResultStatus.PROVED
    assert outcome.result.authority is ResultAuthority.THEOREM
    kernel_stage = outcome.stage(HammerStage.KERNEL_RECEIPTS)
    assert kernel_stage is not None
    assert kernel_stage.status is HammerStageStatus.VERIFIED
    assert kernel_stage.authority is ResultAuthority.THEOREM
    assert invocations


def test_hammer_full_pipeline_keeps_stages_ordered_and_distinct():
    def unknown_solver(*, translation, premises, bounds):
        return {"verdict": "unknown"}

    def recon(*, candidate, native_source, bounds):
        return {
            "kernel_accepted": False,
            "diagnostics": ["reconstruction did not discharge goal"],
            "checked_source_digest": stable_digest({"s": native_source}),
        }

    kernel = IsabelleKernelBackend(
        incomplete_disposition=IsabelleAuthorityDisposition.DOWNGRADE,
        native_probe=lambda: _available_native(),
    )
    hammer = HammerBackend(
        solver_providers=[],
        reconstructor_providers=[],
        isabelle_kernel=kernel,
    )
    hammer.register_solver_id("z3", available=True, runner=unknown_solver)
    hammer.register_reconstructor_id(
        "isabelle", available=True, runner=recon
    )

    outcome = hammer.run(
        _request(
            family="software_verification",
            encoding="isabelle",
            source=ISABELLE_SORRY,
            backend_id="hammer",
            path="Goal.thy",
            extra_payload={
                "goal_statement": "n = n",
                "native_source": ISABELLE_SORRY,
                "itp": "isabelle",
                "solver_providers": ["z3"],
            },
        )
    )

    stage_names = [s.stage for s in outcome.stages]
    assert stage_names == [
        HammerStage.PREMISE_SELECTION,
        HammerStage.SMT_ATP_SEARCH,
        HammerStage.PROOF_CANDIDATES,
        HammerStage.RECONSTRUCTION,
        HammerStage.KERNEL_RECEIPTS,
    ]
    # Premise selection skipped without corpus is still a real stage receipt.
    assert outcome.stage(HammerStage.PREMISE_SELECTION).status in {
        HammerStageStatus.SKIPPED,
        HammerStageStatus.COMPLETED,
        HammerStageStatus.FAILED,
    }
    # Sorry path: kernel must not prove.
    assert outcome.result.status is not ResultStatus.PROVED
    assert outcome.result.authority is ResultAuthority.CANDIDATE
    assert outcome.kernel_outcome is not None
    assert outcome.kernel_outcome.receipt.accepted is False
    assert outcome.kernel_outcome.receipt.path_metadata.theory_path == "Incomplete.thy"
    assert outcome.provider_registry is not None
    assert "z3" in outcome.provider_registry.solver_ids()
    assert "isabelle" in outcome.provider_registry.reconstructor_ids()


def test_hammer_stage_receipt_forbids_theorem_authority_outside_kernel():
    with pytest.raises(HammerBackendError):
        from ipfs_datasets_py.logic.hammers.backend import HammerStageReceipt

        HammerStageReceipt(
            stage=HammerStage.SMT_ATP_SEARCH,
            status=HammerStageStatus.CANDIDATE_ONLY,
            authority=ResultAuthority.THEOREM,
        )


def test_interface_versions_match_objective_contracts():
    assert HAMMER_BACKEND_VERSION == "HammerBackend@1"
    assert ISABELLE_KERNEL_BACKEND_VERSION == "IsabelleKernelBackend@1"
    assert HammerBackend.interface_version == HAMMER_BACKEND_VERSION
    assert IsabelleKernelBackend.interface_version == ISABELLE_KERNEL_BACKEND_VERSION
