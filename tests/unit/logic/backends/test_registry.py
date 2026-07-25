"""Contract tests for side-effect-free proof backend adapters."""

from __future__ import annotations

import os
import shutil
from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.backends.cvc5.compiler import (
    CVC5Backend,
    CVC5Compiler,
)
from ipfs_datasets_py.logic.backends.registry import (
    BackendRunnerOutput,
    CallableProofBackend,
    DuplicateBackendError,
    ProofBackendRegistry,
)
from ipfs_datasets_py.logic.backends.z3.compiler import Z3Backend, Z3Compiler
from ipfs_datasets_py.logic.ir_core.claims import (
    Assumption,
    IRClaim,
    ProofObligation,
)
from ipfs_datasets_py.logic.ir_core.protocols import (
    AttemptStatus,
    BackendCapabilities,
    BackendRequest,
    ExecutionBounds,
    ProofBackend,
    ProofResult,
    QueryKind,
    ResultStatus,
    SatisfiabilityResult,
)


def _claim(logic_family: str = "first_order") -> IRClaim:
    return IRClaim(
        claim_id="claim:modus-ponens",
        declaration_id="declaration:registry-tests",
        statement="Modus ponens is valid.",
        assumptions=(
            Assumption("assumption:p", "p"),
            Assumption("assumption:p-implies-q", "p implies q"),
        ),
        obligations=(
            ProofObligation(
                obligation_id="obligation:q",
                statement="q",
                assumption_ids=(
                    "assumption:p",
                    "assumption:p-implies-q",
                ),
                logic_family=logic_family,
            ),
        ),
    )


def _request(
    *,
    backend_id: str = "z3",
    query_kind: QueryKind = QueryKind.THEOREM_PROOF,
    logic_family: str = "first_order",
    payload: dict[str, object] | None = None,
) -> BackendRequest:
    return BackendRequest.for_claim(
        _claim(logic_family),
        "obligation:q",
        request_id=f"request:{backend_id}:{query_kind.value}:{logic_family}",
        query_kind=query_kind,
        bounds=ExecutionBounds(
            timeout_ms=100,
            max_steps=1_000,
            max_memory_bytes=1_000_000,
            max_output_bytes=4_096,
        ),
        payload=payload
        or {
            "encoding": "smt-expression/v1",
            "declarations": [
                "(declare-const p Bool)",
                "(declare-const q Bool)",
            ],
            "assumptions": ["p", "(=> p q)"],
            "goal": "q",
        },
        requested_backend_id=backend_id,
    )


def _runner(stdout: str, *, returncode: int = 0, **usage: int):
    def run(_compiled, _request):
        return BackendRunnerOutput(
            stdout=stdout,
            returncode=returncode,
            elapsed_ms=usage.get("elapsed_ms", 3),
            steps=usage.get("steps", 0),
            peak_memory_bytes=usage.get("peak_memory_bytes", 0),
        )

    return run


def test_capability_discovery_does_not_probe_run_compile_or_write(tmp_path) -> None:
    calls: list[str] = []
    marker = tmp_path / "unexpected-side-effect"

    def side_effect(name: str):
        def invoke(*_args):
            calls.append(name)
            marker.write_text(name, encoding="utf-8")
            if name == "probe":
                return True
            raise AssertionError(f"{name} must not run during capability discovery")

        return invoke

    backend = CallableProofBackend(
        backend_id="fake",
        backend_version="fake/v1",
        capabilities=BackendCapabilities(
            logic_families=("first_order",),
            query_kinds=(QueryKind.THEOREM_PROOF,),
            deterministic=True,
        ),
        compiler=side_effect("compiler"),
        runner=side_effect("runner"),
        availability_probe=side_effect("probe"),
    )
    registry = ProofBackendRegistry((backend,))
    request = replace(_request(), requested_backend_id="fake")

    assert isinstance(backend, ProofBackend)
    assert registry.capabilities["fake"] == backend.capabilities
    assert registry.capabilities_for("fake") == backend.capabilities
    assert registry.supporting(request) == ("fake",)
    assert backend.supports(request)
    assert calls == []
    assert not marker.exists()


@pytest.mark.parametrize(
    ("stdout", "expected_status"),
    [
        ("unsat\n", ResultStatus.PROVED),
        ("sat\n(model)\n", ResultStatus.DISPROVED),
    ],
)
def test_fake_backend_records_success_and_counterexample(
    stdout: str, expected_status: ResultStatus
) -> None:
    request = _request()
    registry = ProofBackendRegistry(
        (Z3Backend(runner=_runner(stdout), availability_probe=lambda: True),)
    )

    attempt, result = registry.run(request)

    assert attempt.status is AttemptStatus.SUCCEEDED
    assert isinstance(result, ProofResult)
    assert result.status is expected_status
    assert attempt.request_digest == request.digest
    assert result.attempt_digest == attempt.digest
    assert result.output_digest == attempt.output_digest
    assert result.assumption_ids == request.assumption_ids
    assert result.bounds == request.bounds
    assert result.payload["solver_output"] == stdout


def test_fake_backend_records_unsupported_without_calling_runner() -> None:
    calls: list[str] = []
    request = _request(logic_family="higher_order")
    backend = Z3Backend(
        runner=lambda *_args: calls.append("runner"),  # type: ignore[arg-type]
        availability_probe=lambda: True,
    )

    attempt, result = ProofBackendRegistry((backend,)).run(request)

    assert calls == []
    assert attempt.status is AttemptStatus.FAILED
    assert result.status is ResultStatus.ERROR
    assert result.payload["solver_result"] == "unsupported"
    assert any("does not support" in item for item in attempt.diagnostics)


def test_fake_backend_records_unavailable_without_compiling_or_running() -> None:
    calls: list[str] = []
    backend = Z3Backend(
        compiler=lambda _request: calls.append("compiler"),  # type: ignore[arg-type]
        runner=lambda *_args: calls.append("runner"),  # type: ignore[arg-type]
        availability_probe=lambda: False,
    )

    attempt, result = ProofBackendRegistry((backend,)).run(_request())

    assert calls == []
    assert attempt.status is AttemptStatus.UNAVAILABLE
    assert result.status is ResultStatus.UNKNOWN
    assert result.payload["solver_result"] == "unavailable"


def test_fake_backend_records_timeout() -> None:
    def time_out(_compiled, request):
        raise TimeoutError(f"exceeded {request.bounds.timeout_ms} ms")

    attempt, result = ProofBackendRegistry(
        (Z3Backend(runner=time_out, availability_probe=lambda: True),)
    ).run(_request())

    assert attempt.status is AttemptStatus.TIMED_OUT
    assert attempt.usage.elapsed_ms == attempt.bounds.timeout_ms
    assert result.status is ResultStatus.UNKNOWN
    assert result.payload["solver_result"] == "timeout"


def test_reported_resource_overflow_fails_closed() -> None:
    request = _request()
    attempt, result = ProofBackendRegistry(
        (
            Z3Backend(
                runner=_runner(
                    "unsat\n",
                    steps=request.bounds.max_steps + 1,
                ),
                availability_probe=lambda: True,
            ),
        )
    ).run(request)

    assert attempt.status is AttemptStatus.FAILED
    assert result.status is ResultStatus.ERROR
    assert result.payload["solver_result"] == "resource_limit_exceeded"
    assert not result.is_theorem_proof


@pytest.mark.parametrize(
    "runner",
    [
        _runner("definitely-not-a-solver-result\n"),
        _runner("sat\nunsat\n"),
        _runner("sat\n", returncode=2),
        lambda _compiled, _request: {"stdout": "unsat\n"},
    ],
)
def test_fake_backend_fails_closed_on_malformed_output(runner) -> None:
    attempt, result = ProofBackendRegistry(
        (Z3Backend(runner=runner, availability_probe=lambda: True),)
    ).run(_request())

    assert attempt.status is AttemptStatus.FAILED
    assert result.status is ResultStatus.ERROR
    assert not result.is_theorem_proof
    assert attempt.diagnostics


def test_registry_fails_closed_on_malformed_backend_contract() -> None:
    class MalformedBackend:
        backend_id = "malformed"
        backend_version = "malformed/v1"
        capabilities = BackendCapabilities(
            logic_families=("first_order",),
            query_kinds=(QueryKind.THEOREM_PROOF,),
        )

        def supports(self, _request):
            return True

        def run(self, _request):
            return {"verdict": "proved"}

    request = replace(_request(), requested_backend_id="malformed")
    attempt, result = ProofBackendRegistry((MalformedBackend(),)).run(request)

    assert attempt.status is AttemptStatus.FAILED
    assert result.status is ResultStatus.ERROR
    assert result.payload["solver_result"] == "malformed_backend_contract"


def test_satisfiability_request_uses_satisfiability_result_family() -> None:
    request = _request(query_kind=QueryKind.SATISFIABILITY)
    attempt, result = ProofBackendRegistry(
        (Z3Backend(runner=_runner("sat\n"), availability_probe=lambda: True),)
    ).run(request)

    assert attempt.status is AttemptStatus.SUCCEEDED
    assert isinstance(result, SatisfiabilityResult)
    assert result.status is ResultStatus.SATISFIABLE
    assert not result.is_theorem_proof


def test_z3_and_cvc5_compilers_lower_the_same_neutral_obligation() -> None:
    request = _request(backend_id="z3")
    cvc5_request = replace(request, requested_backend_id="cvc5")

    z3_compilation = Z3Compiler().compile(request)
    cvc5_compilation = CVC5Compiler().compile(cvc5_request)

    for compilation in (z3_compilation, cvc5_compilation):
        assert "(declare-const p Bool)" in compilation.source
        assert "(assert p)" in compilation.source
        assert "(assert (=> p q))" in compilation.source
        assert "(assert (not q))" in compilation.source
        assert compilation.source.rstrip().endswith("(check-sat)")
    assert z3_compilation.request_digest == request.digest
    assert cvc5_compilation.request_digest == cvc5_request.digest


def test_registry_rejects_duplicate_backend_ids() -> None:
    backend = Z3Backend(runner=_runner("unsat\n"))
    registry = ProofBackendRegistry((backend,))

    with pytest.raises(DuplicateBackendError, match="already registered"):
        registry.register(backend)


def test_default_adapters_are_created_without_availability_checks(monkeypatch) -> None:
    calls: list[str] = []

    def forbidden_which(_name):
        calls.append("which")
        raise AssertionError("construction and capabilities must not probe PATH")

    monkeypatch.setattr(shutil, "which", forbidden_which)
    registry = ProofBackendRegistry((Z3Backend(), CVC5Backend()))

    assert tuple(registry) == ("cvc5", "z3")
    assert set(registry.capabilities) == {"cvc5", "z3"}
    assert calls == []


@pytest.mark.skipif(
    os.environ.get("IPFS_DATASETS_RUN_SOLVER_DIFFERENTIAL") != "1"
    or shutil.which("z3") is None
    or shutil.which("cvc5") is None,
    reason=(
        "scheduled differential check requires "
        "IPFS_DATASETS_RUN_SOLVER_DIFFERENTIAL=1 and both solver CLIs"
    ),
)
def test_scheduled_real_z3_cvc5_differential_agreement() -> None:
    """Optional scheduled evidence; never a unit-test dependency."""

    z3_request = _request(
        backend_id="z3",
        payload={"encoding": "smt-expression/v1", "goal": "true"},
    )
    cvc5_request = replace(z3_request, requested_backend_id="cvc5")
    registry = ProofBackendRegistry((Z3Backend(), CVC5Backend()))

    z3_attempt, z3_result = registry.run(z3_request)
    cvc5_attempt, cvc5_result = registry.run(cvc5_request)

    assert z3_attempt.status is AttemptStatus.SUCCEEDED
    assert cvc5_attempt.status is AttemptStatus.SUCCEEDED
    assert z3_result.status is ResultStatus.PROVED
    assert cvc5_result.status is ResultStatus.PROVED
