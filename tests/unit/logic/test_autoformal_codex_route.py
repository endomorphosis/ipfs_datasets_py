"""Provider qualification cannot count output prose as successful repair."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def qualifier():
    scripts = Path(__file__).resolve().parents[3] / "scripts/ops/legal_ir"
    import sys
    sys.path.insert(0, str(scripts))
    try:
        spec = importlib.util.spec_from_file_location("route_qualification_test", scripts / "qualify_autoformal_codex_route.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.path.remove(str(scripts))


@pytest.mark.parametrize("options", [[], ["name=seccomp"], ["name=rootless-ish"], "name=rootless", None])
def test_rootless_must_be_explicit(qualifier, options):
    with pytest.raises(ValueError, match="rootless"):
        qualifier.require_rootless(options)


def test_rootless_exact_security_option(qualifier):
    qualifier.require_rootless(["name=seccomp", "name=rootless"])


@pytest.mark.parametrize("source", [
    "def add_one(value):\n    return value - 1\n",
    "import os\ndef add_one(value):\n    return value + 1\n",
    "def add_one(value):\n    return value + 1\nraise RuntimeError('side effect')\n",
    "def add_one(value):\n    return value + 1\n\nREADY\n",
    "def add_one(value): return eval('value + 1')",
    "def add_one(value):\n  else:\n",
])
def test_fixture_check_rejects_wrong_or_extra_code_without_importing(qualifier, tmp_path, source):
    target = tmp_path / "probe.py"
    target.write_text(source)
    assert qualifier.fixture_is_correct(target) is False


def test_fixture_check_accepts_only_expected_ast(qualifier, tmp_path):
    target = tmp_path / "probe.py"
    target.write_text("def add_one(value):\n    return value + 1\n")
    assert qualifier.fixture_is_correct(target)
    assert not qualifier.fixture_is_correct(tmp_path / "missing.py")


def test_boundary_probe_uses_real_git_directory_and_no_credentials(qualifier):
    assert "auth.json" not in qualifier.BOUNDARY_PROBE
    assert "CapEff:" in qualifier.BOUNDARY_PROBE
    assert "NoNewPrivs:" in qualifier.BOUNDARY_PROBE
    assert "docker_socket_not_visible" in qualifier.BOUNDARY_PROBE


@pytest.mark.parametrize("store_kind,reason", [
    ("opaque_id", "database store is not canonical"),
    ("sibling_database", "database store escapes repository"),
])
def test_native_external_validation_rejects_incompatible_layout_before_execution(
    tmp_path, monkeypatch, store_kind, reason,
):
    """Qualification must not silently switch to an unsandboxed validator.

    These are layout unit tests, not evidence of host/image qualification.
    The live qualification receipt separately checks the actual Docker image.
    """
    from types import SimpleNamespace
    from ipfs_accelerate_py.agent_supervisor.runtime import multi_supervisor_runner as runner
    from ipfs_accelerate_py.agent_supervisor.todo_daemon import implementation_daemon as native

    repository = tmp_path / "candidate"
    repository.mkdir()
    control = tmp_path / "control"
    control.mkdir()
    # The native store-ID parser disallows leading '/', so use a parseable
    # relative escape to exercise containment (not merely identifier syntax).
    store_id = "autoformal-test-store" if store_kind == "opaque_id" else "state/../../control/control.duckdb"
    program = runner.DatabaseProgramConfig(
        authority_mode="embedded", task_source_kind="duckdb", store_id=store_id,
        failover_policy="fail_closed",
    )
    for key, value in program.environment(repository_root=repository).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv(native._LIFECYCLE_REPOSITORY_ROOT_ENV, str(repository))
    monkeypatch.setenv(native.PROVIDER_EXTERNAL_ISOLATION_ENV, "unit-test-only")
    monkeypatch.setattr(native, "validate_external_provider_isolation_config", lambda value: None)

    def forbid_execution(*args, **kwargs):
        pytest.fail("incompatible authority layout must fail before any validator process")

    monkeypatch.setattr(native.subprocess, "Popen", forbid_execution)
    result = native.PortalImplementationDaemon._validation_command_runner(
        spec=SimpleNamespace(command="python3 -m pytest -q", raw_command="python3 -m pytest -q"),
        workspace_path=repository, timeout_seconds=30, environment={},
    )
    assert result["returncode"] == 75
    assert result["infrastructure_failure"] is True
    assert result["error"] == "external_validation_isolation_unavailable"
    assert reason in result["reason"]
