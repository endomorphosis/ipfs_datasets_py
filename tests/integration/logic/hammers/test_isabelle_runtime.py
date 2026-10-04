"""Live Isabelle qualification plus deterministic setup/readiness checks."""
import pytest

from ipfs_datasets_py.logic.external_provers.isabelle_runtime import CHECK_MARKER, add_kernel_audit, theory_command
from ipfs_datasets_py.logic.external_provers.isabelle_setup import ensure_isabelle_ready
from ipfs_datasets_py.logic.hammers.frontends.isabelle import IsabelleFrontend
from ipfs_datasets_py.logic.hammers.models import HammerPolicy, HammerRequest, ITPKind, ProofCandidateRecord
from ipfs_datasets_py.logic.hammers.reconstructors.isabelle import IsabelleReconstructor, _evaluate_isabelle_outcome
from ipfs_datasets_py.logic.hammers.portfolio import SolverProcessOutcome


@pytest.fixture(scope="module")
def live_frontend():
    frontend = IsabelleFrontend(timeout=60)
    if not frontend.capability().available:
        pytest.skip("modern Isabelle process_theories runtime is unavailable")
    return frontend


@pytest.mark.parametrize("statement,accepted", [("(n::nat) = n", True), ("(0::nat) = 1", False)])
def test_live_capture_reconstruction_and_kernel_audit(live_frontend, statement, accepted):
    source = f'theory IPFSLiveCheck\nimports Main\nbegin\nlemma checked: "{statement}"\nsorry\nend\n'
    snapshot = live_frontend.snapshot_goal(source, theorem_id="checked")
    assert snapshot.raw_native_output and "process_theories" in snapshot.native_command
    request = HammerRequest(request_id="live-isabelle", itp=ITPKind.ISABELLE,
                            theorem_id="checked", goal_statement=snapshot.goal_text,
                            corpus_revision="live-test", policy=HammerPolicy(timeout_seconds=60))
    candidate = ProofCandidateRecord(candidate_id="candidate", request_id=request.request_id,
                                     solver_attempt_id="untrusted-proposal", premise_ids=[])
    record, evidence, lock = IsabelleReconstructor(timeout=60).reconstruct(
        request=request, candidate=candidate, goal_snapshot=snapshot, native_source=source)
    assert record.kernel_accepted is accepted
    assert "quick_and_dirty=false" in evidence.command
    if accepted:
        assert CHECK_MARKER in evidence.stdout
    else:
        assert record.failure_reason


def test_live_setup_smoke_uses_existing_runtime_without_install(live_frontend):
    report = ensure_isabelle_ready(smoke=True, timeout=60)
    assert report["ready"] and report["smoke"]["accepted"], report
    assert report["installation"] is None


def test_live_canonical_kernel_backend_checks_the_named_theorem(live_frontend):
    from ipfs_datasets_py.logic.backends.kernel.isabelle import IsabelleKernelBackend
    from ipfs_datasets_py.logic.backends.results import ResultStatus
    from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
    from ipfs_datasets_py.logic.ir_core.protocols import BackendRequest, ExecutionBounds, QueryKind
    request = BackendRequest(
        request_id="live-kernel", claim_id="claim", declaration_id="checked",
        claim_digest="1" * 64, obligation_id="obligation", obligation_digest="2" * 64,
        assumption_ids=(), logic_family="isabelle", query_kind=QueryKind.THEOREM_PROOF,
        # Isabelle runs JVM and Poly/ML processes; an SMT-sized virtual-address
        # cap cannot accommodate their runtime mappings. The backend monitors tree RSS.
        bounds=ExecutionBounds(timeout_ms=60_000, max_memory_bytes=2 * 1024**3),
        payload=FrozenMap({"encoding": "isabelle", "source":
                          'theory IPFSCanonicalCheck\nimports Main\nbegin\nlemma checked: "True" by simp\nend\n'}),
        requested_backend_id="isabelle",
    )
    outcome = IsabelleKernelBackend().run(request)
    assert outcome.result.status is ResultStatus.PROVED, outcome.receipt.diagnostics
    assert outcome.receipt.accepted
    assert outcome.receipt.toolchain.version == "Isabelle2025-2"


def test_success_exit_without_named_theorem_audit_is_rejected():
    accepted, reason = _evaluate_isabelle_outcome(SolverProcessOutcome(command=["isabelle"], returncode=0,
                                                                      stdout="Finished Draft"))
    assert not accepted and "audit" in reason


def test_setup_does_not_install_when_unavailable(monkeypatch):
    from ipfs_datasets_py.logic.external_provers import isabelle_setup
    from ipfs_datasets_py.logic.backends.installers import isabelle as installer
    monkeypatch.setattr(installer, "ensure_isabelle", lambda **_: pytest.fail("installed during inspection"))
    result = ensure_isabelle_ready(install_root="/nonexistent/isabelle-preparation-fixture", timeout=2)
    assert not result["ready"] and result["installation"] is None


def test_theory_paths_are_validated_and_audit_is_inserted_inside_theory():
    with pytest.raises(ValueError):
        theory_command("isabelle", "../../bad", ".")
    source = 'theory A\nimports Main\nbegin\nlemma ok: "True" by simp\nend\n'
    checked = add_kernel_audit(source, "ok")
    assert checked.index(CHECK_MARKER) < checked.rindex("end")
    with pytest.raises(ValueError):
        add_kernel_audit(source, "ok; injected")


def test_capability_projects_bounded_readiness_failure(monkeypatch):
    from types import SimpleNamespace
    from ipfs_datasets_py.logic.hammers.frontends import isabelle as module
    from tests.integration.logic.hammers.isabelle_execution_fixtures import unavailable_operation
    operation = unavailable_operation()
    operation.reason_code = "isabelle_theory_processor_unavailable"
    operation.native_runtime = {"executable": "/fake/isabelle", "version": "Isabelle2025-2"}
    monkeypatch.setattr(module, "run_isabelle_operation", lambda **_: operation)
    capability = IsabelleFrontend().capability()
    assert not capability.available
    assert capability.executables["isabelle"]["found"]
    assert capability.unavailable_reason == "isabelle_process_theories_not_ready"


def test_lazy_frontend_installs_only_on_explicit_first_use(monkeypatch):
    from ipfs_datasets_py.logic.hammers.frontends import isabelle as module
    from ipfs_datasets_py.logic.hammers.frontends.base import FrontendUnavailableError
    from tests.integration.logic.hammers.isabelle_execution_fixtures import unavailable_operation
    calls = []
    def operation(**kwargs):
        calls.append(kwargs)
        return unavailable_operation()
    monkeypatch.setattr(module, "run_isabelle_operation", operation)
    source = 'theory A\nimports Main\nbegin\nlemma ok: "True"\nsorry\nend\n'
    frontend = IsabelleFrontend(auto_install=True)
    assert not frontend.capability().available
    assert calls[0]["mode"] == "command" and not calls[0].get("auto_install", False)
    with pytest.raises(FrontendUnavailableError):
        frontend.snapshot_goal(source, theorem_id="ok")
    assert len(calls) == 2 and calls[1]["auto_install"]
    assert calls[1]["mode"] == "capture" and "print_state" in calls[1]["source"]


def test_installer_does_not_reuse_incompatible_runtime(monkeypatch):
    from types import SimpleNamespace
    from ipfs_datasets_py.logic.integration.bridges import prover_installer
    from ipfs_datasets_py.logic.backends.installers import isabelle_installation as installer
    calls = []
    monkeypatch.setattr(prover_installer, "_which", lambda _: pytest.fail("unadmitted discovery"))
    monkeypatch.setattr(installer, "ensure_isabelle_installation",
        lambda **kw: calls.append(kw) or SimpleNamespace(usable=False, status="blocked"))
    assert not prover_installer.ensure_isabelle(yes=False, strict=True)
    assert len(calls) == 1 and calls[0]["yes"] is False
