"""Tests for hammer backend availability checks."""

from __future__ import annotations

import subprocess

from ipfs_datasets_py.logic.integration.reasoning.hammer import (
    CallableHammerBackendRunner,
    HammerBackendResult,
    HammerBackendStatus,
    SubprocessHammerBackendRunner,
)
from ipfs_datasets_py.logic.integration.reasoning.hammer_backends import (
    HAMMER_BACKEND_HEALTH_SCHEMA_VERSION,
    backend_health_for_runners,
    check_hammer_backend_availability,
    check_hammer_backend_health,
    default_hammer_subprocess_backends,
    hammer_backend_health_summary,
    lazy_install_hammer_backend,
)


def test_backend_availability_reports_missing_solvers_without_raising() -> None:
    health = check_hammer_backend_health(
        ["z3", "cvc5", "vampire", "e_prover", "lean", "coq", "isabelle"],
        resolver=lambda executable: None,
    )
    payload = hammer_backend_health_summary(health)

    assert len(health) == 7
    assert payload["schema_version"] == HAMMER_BACKEND_HEALTH_SCHEMA_VERSION
    assert payload["available_count"] == 0
    assert set(payload["unavailable_routes"]) == {
        "z3",
        "cvc5",
        "vampire",
        "e_prover",
        "lean",
        "coq",
        "isabelle",
    }
    assert all(item.installer_available for item in health)


def test_backend_availability_uses_injected_resolver_for_deterministic_probe() -> None:
    health = check_hammer_backend_availability(
        "z3",
        resolver=lambda executable: f"/opt/bin/{executable}",
    )

    assert health.available is True
    assert health.name == "z3"
    assert health.resolved_path == "/opt/bin/z3"
    assert health.problem_format == "smt-lib"
    assert health.to_dict()["install_command"]


def test_default_hammer_subprocess_backends_preserve_unavailable_routes_for_fail_closed_runs() -> None:
    runners = default_hammer_subprocess_backends()

    assert [runner.name for runner in runners] == ["z3", "cvc5", "vampire", "e_prover"]
    assert {runner.problem_format for runner in runners} == {"smt-lib", "tptp-fof"}


def test_backend_health_for_runtime_and_subprocess_runners() -> None:
    def _run(translation, timeout_seconds):
        return HammerBackendResult(
            backend="fake",
            status=HammerBackendStatus.UNKNOWN,
            proved=False,
            elapsed_seconds=0.0,
            translation_format=translation.target_format,
        )

    health = backend_health_for_runners(
        [
            CallableHammerBackendRunner("fake", "smt-lib", _run),
            SubprocessHammerBackendRunner(
                name="z3",
                executable="z3",
                problem_format="smt-lib",
                suffix=".smt2",
            ),
        ],
        resolver=lambda executable: f"/opt/bin/{executable}" if executable == "z3" else None,
    )

    by_name = {item.name: item for item in health}
    assert by_name["fake"].available is True
    assert by_name["fake"].route_type == "runtime_runner"
    assert by_name["z3"].available is True
    assert by_name["z3"].resolved_path == "/opt/bin/z3"


def test_lazy_install_hook_is_explicit_and_side_effect_injectable() -> None:
    calls = []

    def _runner(command, timeout):
        calls.append((tuple(command), timeout))
        return subprocess.CompletedProcess(list(command), 0, "", "")

    health = lazy_install_hammer_backend("z3", runner=_runner, timeout_seconds=12.0)

    assert calls
    assert calls[0][0] == ("python", "-m", "pip", "install", "z3-solver")
    assert calls[0][1] == 12.0
    assert health.name == "z3"

