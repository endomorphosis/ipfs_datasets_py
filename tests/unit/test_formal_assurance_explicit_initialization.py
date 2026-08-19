"""FACP-022: Explicit Datasets initialization and install gate.

Acceptance coverage:
- Core import passes the sandbox purity probe (after package-root fan-in).
- Installation requires an explicit authorized call and state root.
- Missing dependencies return typed non-success (Unavailable / Failed).
- Legacy opt-in cannot silently default on.
"""

from __future__ import annotations

import json
import os
import resource
import subprocess
import sys
import tempfile
import textwrap
import time
import warnings
from pathlib import Path
from typing import Any

import pytest

TASK_ID = "FACP-022"
GOAL_ID = "FACP-G210"
BUNDLE = "facp/migration/datasets-init"
EVIDENCE_ID = "facp/datasets-explicit-initialization@1"

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
_WORKSPACE_ROOT = Path(__file__).resolve().parents[4]
_INIT_MODULE = (
    _PACKAGE_ROOT / "ipfs_datasets_py" / "assurance" / "initialization.py"
)

FORBIDDEN_SUCCESS_ON_FAILURE = frozenset(
    {"success", "ok", "passed", "pure", "hermetic", "production_supported"}
)


def _load_initialization_module():
    """Load assurance.initialization without executing package-root ``__init__``."""
    import importlib.util
    import types

    pkg_name = "ipfs_datasets_py"
    assurance_name = "ipfs_datasets_py.assurance"
    mod_name = "ipfs_datasets_py.assurance.initialization"
    pkg_dir = _PACKAGE_ROOT / "ipfs_datasets_py"
    assurance_dir = pkg_dir / "assurance"

    if pkg_name not in sys.modules or not hasattr(sys.modules[pkg_name], "__path__"):
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(pkg_dir)]  # type: ignore[attr-defined]
        pkg.__file__ = str(pkg_dir / "__init__.py")
        sys.modules[pkg_name] = pkg
    if assurance_name not in sys.modules:
        assurance = types.ModuleType(assurance_name)
        assurance.__path__ = [str(assurance_dir)]  # type: ignore[attr-defined]
        assurance.__package__ = assurance_name
        sys.modules[assurance_name] = assurance

    if mod_name in sys.modules and hasattr(sys.modules[mod_name], "initialize_datasets"):
        return sys.modules[mod_name]

    spec = importlib.util.spec_from_file_location(mod_name, _INIT_MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    # Re-export on parent namespace for attribute access.
    sys.modules[assurance_name].initialization = module  # type: ignore[attr-defined]
    return module


@pytest.fixture(autouse=True)
def _reset_assurance_state():
    if str(_PACKAGE_ROOT) not in sys.path:
        sys.path.insert(0, str(_PACKAGE_ROOT))
    init = _load_initialization_module()
    init.reset_initialization_state(remove_fan_in=True)
    # Clear legacy env so tests control opt-in explicitly.
    for key in (
        "IPFS_DATASETS_AUTO_INSTALL",
        "IPFS_KIT_AUTO_INSTALL_DEPS",
        "IPFS_AUTO_INSTALL",
        "IPFS_DATASETS_ENSURE_INSTALLER",
        "IPFS_DATASETS_PY_MINIMAL_IMPORTS",
        "IPFS_DATASETS_PY_BENCHMARK",
    ):
        os.environ.pop(key, None)
    yield
    init.reset_initialization_state(remove_fan_in=True)


def test_initialization_module_exists_and_exports_contract():
    assert _INIT_MODULE.is_file(), f"missing declared output: {_INIT_MODULE}"
    init = _load_initialization_module()

    assert init.TASK_ID == TASK_ID
    assert init.GOAL_ID == GOAL_ID
    assert init.BUNDLE == BUNDLE
    assert init.EVIDENCE_ID == EVIDENCE_ID
    for name in (
        "initialize_datasets",
        "ensure_dependency",
        "apply_package_root_fan_in",
        "hermetic_core_import_env",
        "InitializationOutcome",
    ):
        assert hasattr(init, name), name


def test_cold_import_of_assurance_initialization_is_pure():
    """Importing the assurance initializer must not install or mutate env."""
    script = textwrap.dedent(
        f"""
        import os, sys, json, importlib.util, types
        package_root = {_PACKAGE_ROOT.as_posix()!r}
        init_path = { _INIT_MODULE.as_posix()!r }
        for k in (
            "IPFS_DATASETS_AUTO_INSTALL",
            "IPFS_KIT_AUTO_INSTALL_DEPS",
            "IPFS_AUTO_INSTALL",
        ):
            os.environ.pop(k, None)
        for n in list(sys.modules):
            if n == "ipfs_datasets_py" or n.startswith("ipfs_datasets_py."):
                del sys.modules[n]
        pkg = types.ModuleType("ipfs_datasets_py")
        pkg.__path__ = [package_root + "/ipfs_datasets_py"]
        sys.modules["ipfs_datasets_py"] = pkg
        assurance = types.ModuleType("ipfs_datasets_py.assurance")
        assurance.__path__ = [package_root + "/ipfs_datasets_py/assurance"]
        sys.modules["ipfs_datasets_py.assurance"] = assurance
        spec = importlib.util.spec_from_file_location(
            "ipfs_datasets_py.assurance.initialization", init_path
        )
        init = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = init
        spec.loader.exec_module(init)
        after = {{
            "IPFS_DATASETS_AUTO_INSTALL": os.environ.get("IPFS_DATASETS_AUTO_INSTALL"),
            "IPFS_KIT_AUTO_INSTALL_DEPS": os.environ.get("IPFS_KIT_AUTO_INSTALL_DEPS"),
            "IPFS_AUTO_INSTALL": os.environ.get("IPFS_AUTO_INSTALL"),
        }}
        print("FACP022::" + json.dumps({{
            "after": after,
            "initialized": init.is_initialized(),
            "fan_in": init.package_root_fan_in_active(),
            "task_id": init.TASK_ID,
        }}, sort_keys=True))
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(_WORKSPACE_ROOT),
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    line = next(
        ln for ln in completed.stdout.splitlines() if ln.startswith("FACP022::")
    )
    payload = json.loads(line[len("FACP022::") :])
    assert payload["initialized"] is False
    assert payload["fan_in"] is False
    assert payload["after"]["IPFS_DATASETS_AUTO_INSTALL"] is None
    assert payload["after"]["IPFS_KIT_AUTO_INSTALL_DEPS"] is None
    assert payload["task_id"] == TASK_ID


def test_initialize_requires_explicit_state_root():
    init = _load_initialization_module()

    result = init.initialize_datasets(authorize_install=True)
    assert result.outcome == "Failed"
    assert result.code == "missing_state_root"
    assert result.ok is False
    assert result.details.get("implicit_home_forbidden") is True
    assert not init.is_initialized()


def test_initialize_authorized_with_state_root_is_idempotent(tmp_path: Path):
    init = _load_initialization_module()

    state_root = tmp_path / "explicit_state"
    first = init.initialize_datasets(
        state_root=state_root,
        authorize_install=True,
    )
    assert first.outcome == "Observed"
    assert first.code == "initialized"
    assert first.ok is True
    assert state_root.is_dir()
    assert init.is_install_authorized() is True

    second = init.initialize_datasets(
        state_root=state_root,
        authorize_install=True,
    )
    assert second.outcome == "Observed"
    assert second.code == "already_initialized"
    assert second.ok is True


def test_state_root_conflict_is_failed(tmp_path: Path):
    init = _load_initialization_module()

    a = tmp_path / "a"
    b = tmp_path / "b"
    assert init.initialize_datasets(state_root=a, authorize_install=True).ok
    conflict = init.initialize_datasets(state_root=b, authorize_install=True)
    assert conflict.outcome == "Failed"
    assert conflict.code == "state_root_conflict"


def test_missing_dependencies_return_typed_unavailable(tmp_path: Path):
    init = _load_initialization_module()

    state_root = tmp_path / "state"
    missing = init.initialize_datasets(
        state_root=state_root,
        authorize_install=True,
        dependencies={"facp022_definitely_missing_module_xyz": True},
    )
    assert missing.outcome == "Unavailable"
    assert missing.code == "dependency_unavailable"
    assert missing.ok is False
    assert not init.is_initialized()

    # After a clean init, ensure_dependency still types missing modules.
    ok = init.initialize_datasets(state_root=state_root, authorize_install=False)
    assert ok.ok
    probe = init.ensure_dependency("facp022_definitely_missing_module_xyz")
    assert probe.outcome == "Unavailable"
    assert probe.code == "dependency_unavailable"
    assert probe.ok is False


def test_install_without_authorization_returns_failed(tmp_path: Path):
    init = _load_initialization_module()

    state_root = tmp_path / "state"
    init.initialize_datasets(state_root=state_root, authorize_install=False)
    result = init.ensure_dependency(
        "facp022_missing_for_install",
        allow_install=True,
    )
    assert result.outcome == "Failed"
    assert result.code == "install_not_authorized"
    assert result.ok is False


def test_ensure_dependency_before_init_is_unavailable():
    init = _load_initialization_module()

    result = init.ensure_dependency("json")
    assert result.outcome == "Unavailable"
    assert result.code == "not_initialized"


def test_ensure_dependency_present_after_init(tmp_path: Path):
    init = _load_initialization_module()

    init.initialize_datasets(state_root=tmp_path / "state", authorize_install=False)
    result = init.ensure_dependency("json")
    assert result.outcome == "Observed"
    assert result.code == "dependency_present"
    assert result.ok is True


def test_legacy_opt_in_cannot_silently_default_on(tmp_path: Path):
    init = _load_initialization_module()

    # Unset env + init without legacy authorization => gate rejects silent on.
    for key in (
        "IPFS_DATASETS_AUTO_INSTALL",
        "IPFS_KIT_AUTO_INSTALL_DEPS",
        "IPFS_AUTO_INSTALL",
    ):
        os.environ.pop(key, None)

    result = init.initialize_datasets(
        state_root=tmp_path / "state",
        authorize_install=False,
        authorize_legacy_opt_in=False,
    )
    assert result.ok
    assert init.is_legacy_opt_in_authorized() is False
    assert init.legacy_opt_in_cannot_silently_default_on() is True
    # Must not have written silent default-on.
    assert os.environ.get("IPFS_DATASETS_AUTO_INSTALL") not in {"true", "1", "yes", "on"}
    assert os.environ.get("IPFS_KIT_AUTO_INSTALL_DEPS") not in {"1", "true", "yes", "on"}


def test_legacy_opt_in_requires_authorize_install(tmp_path: Path):
    init = _load_initialization_module()

    result = init.initialize_datasets(
        state_root=tmp_path / "state",
        authorize_install=False,
        authorize_legacy_opt_in=True,
    )
    assert result.outcome == "Failed"
    assert result.code == "legacy_opt_in_requires_authorize_install"


def test_explicit_legacy_opt_in_emits_compatibility_warning(tmp_path: Path):
    init = _load_initialization_module()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = init.initialize_datasets(
            state_root=tmp_path / "state",
            authorize_install=True,
            authorize_legacy_opt_in=True,
        )
    assert result.ok
    assert init.is_legacy_opt_in_authorized() is True
    assert any("legacy Datasets auto-install opt-in" in str(w.message) for w in caught)
    assert os.environ.get("IPFS_DATASETS_AUTO_INSTALL") == "true"


def _sandbox_env(sandbox: Path) -> dict[str, str]:
    home = sandbox / "home"
    proj = sandbox / "project"
    state = sandbox / "explicit_state"
    tmp = sandbox / "tmp"
    for path in (
        home,
        proj,
        state,
        tmp,
        home / ".config",
        home / ".cache",
        home / ".local" / "share",
    ):
        path.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["XDG_CONFIG_HOME"] = str(home / ".config")
    env["XDG_CACHE_HOME"] = str(home / ".cache")
    env["XDG_DATA_HOME"] = str(home / ".local" / "share")
    env["XDG_STATE_HOME"] = str(state)
    env["TMPDIR"] = str(tmp)
    env["TMP"] = str(tmp)
    env["TEMP"] = str(tmp)
    env["IPFS_DATASETS_PROJECT_ROOT"] = str(proj)
    env["IPFS_DATASETS_LOCAL_BIN"] = str(proj / "bin")
    env["IPFS_DATASETS_LOCAL_DEPS"] = str(proj / "bin" / ".deps")
    env["FACP022_SANDBOX"] = str(sandbox)
    env["FACP022_PACKAGE_ROOT"] = str(_PACKAGE_ROOT)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["NO_NETWORK"] = "1"
    env["PIP_NO_INDEX"] = "1"
    for key in (
        "IPFS_DATASETS_AUTO_INSTALL",
        "IPFS_KIT_AUTO_INSTALL_DEPS",
        "IPFS_AUTO_INSTALL",
        "IPFS_DATASETS_ENSURE_INSTALLER",
        "IPFS_DATASETS_PY_MINIMAL_IMPORTS",
        "IPFS_DATASETS_PY_BENCHMARK",
        "IPFS_DATASETS_PY_ENABLE_MCP_IMPORTS",
        "IPFS_DATASETS_PY_ENABLE_FASTAPI_IMPORTS",
        "IPFS_DATASETS_PY_ENABLE_LLM_IMPORTS",
        "IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS",
    ):
        env.pop(key, None)
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(_PACKAGE_ROOT), env.get("PYTHONPATH", "")) if part
    )
    return env


def test_core_import_passes_sandbox_after_package_root_fan_in():
    """With FACP-022 fan-in applied first, cold package import stays fail-closed."""
    sandbox = Path(tempfile.mkdtemp(prefix="facp022-"))
    env = _sandbox_env(sandbox)
    script = textwrap.dedent(
        r"""
        import os, sys, json, socket, subprocess, resource, builtins
        from pathlib import Path

        effects = []
        SANDBOX = os.environ["FACP022_SANDBOX"]

        def _record(kind, **fields):
            effects.append({"kind": kind, **fields})

        def _deny_net(api, *a, **k):
            _record("network", api=api)
            raise OSError(f"FACP-022 network denied: {api}")

        socket.create_connection = lambda *a, **k: _deny_net("create_connection", *a, **k)
        socket.getaddrinfo = lambda *a, **k: _deny_net("getaddrinfo", *a, **k)

        def _deny_run(*a, **k):
            cmd = a[0] if a else k.get("args")
            _record("subprocess", cmd=[str(x) for x in cmd] if isinstance(cmd, (list, tuple)) else repr(cmd))
            raise RuntimeError("FACP-022 subprocess denied")

        subprocess.run = _deny_run
        class _DenyPopen:
            def __init__(self, *a, **k):
                _deny_run(*a, **k)
        subprocess.Popen = _DenyPopen

        _orig_mkdir = Path.mkdir
        def _tracked_mkdir(self, *a, **k):
            path = str(self)
            _record("fs_mkdir", path=path)
            if path.startswith(SANDBOX):
                return _orig_mkdir(self, *a, **k)
            raise OSError(f"FACP-022 write denied: {path}")
        Path.mkdir = _tracked_mkdir

        for n in list(sys.modules):
            if n == "ipfs_datasets_py" or n.startswith("ipfs_datasets_py."):
                del sys.modules[n]
        for key in (
            "IPFS_DATASETS_AUTO_INSTALL",
            "IPFS_KIT_AUTO_INSTALL_DEPS",
            "IPFS_AUTO_INSTALL",
            "IPFS_DATASETS_ENSURE_INSTALLER",
            "IPFS_DATASETS_PY_MINIMAL_IMPORTS",
            "IPFS_DATASETS_PY_BENCHMARK",
        ):
            os.environ.pop(key, None)

        # Load FACP-022 initializer without executing package-root __init__.
        import importlib.util, types
        package_root = os.environ["FACP022_PACKAGE_ROOT"]
        init_path = os.path.join(package_root, "ipfs_datasets_py", "assurance", "initialization.py")
        pkg = types.ModuleType("ipfs_datasets_py")
        pkg.__path__ = [os.path.join(package_root, "ipfs_datasets_py")]
        sys.modules["ipfs_datasets_py"] = pkg
        assurance = types.ModuleType("ipfs_datasets_py.assurance")
        assurance.__path__ = [os.path.join(package_root, "ipfs_datasets_py", "assurance")]
        sys.modules["ipfs_datasets_py.assurance"] = assurance
        spec = importlib.util.spec_from_file_location(
            "ipfs_datasets_py.assurance.initialization", init_path
        )
        facp_init = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = facp_init
        spec.loader.exec_module(facp_init)

        # Package-root fan-in BEFORE real core import (FACP-022).
        fan = facp_init.apply_package_root_fan_in()
        assert fan.ok, fan.to_dict()

        # Drop the namespace shell so the real package __init__ executes under fan-in.
        for n in list(sys.modules):
            if n == "ipfs_datasets_py" or (
                n.startswith("ipfs_datasets_py.")
                and n != "ipfs_datasets_py.assurance.initialization"
            ):
                # Keep only the assurance initializer module object via alternate bind.
                del sys.modules[n]
        sys.modules["facp022_init"] = facp_init

        before_env = {
            "IPFS_DATASETS_AUTO_INSTALL": os.environ.get("IPFS_DATASETS_AUTO_INSTALL"),
            "IPFS_KIT_AUTO_INSTALL_DEPS": os.environ.get("IPFS_KIT_AUTO_INSTALL_DEPS"),
        }
        before_path = os.environ.get("PATH", "")
        import ipfs_datasets_py  # noqa: F401
        after_env = {
            "IPFS_DATASETS_AUTO_INSTALL": os.environ.get("IPFS_DATASETS_AUTO_INSTALL"),
            "IPFS_KIT_AUTO_INSTALL_DEPS": os.environ.get("IPFS_KIT_AUTO_INSTALL_DEPS"),
        }
        after_path = os.environ.get("PATH", "")
        before_parts = before_path.split(os.pathsep) if before_path else []
        after_parts = after_path.split(os.pathsep) if after_path else []
        path_delta = [p for p in after_parts if p not in before_parts]

        # Purity oracle for DS-IMPORT-001 / DS-IMPORT-002 style effects.
        matched = []
        if after_env.get("IPFS_DATASETS_AUTO_INSTALL") == "true":
            matched.append("environment_write:IPFS_DATASETS_AUTO_INSTALL=true")
        if after_env.get("IPFS_KIT_AUTO_INSTALL_DEPS") in {"1", "true"}:
            matched.append("environment_write:IPFS_KIT_AUTO_INSTALL_DEPS")
        if any(e.get("kind") == "fs_mkdir" and "/bin" in str(e.get("path", "")) for e in effects):
            # Allow sandbox-local mkdirs under FACP022_SANDBOX project only when
            # they are not installer bin/deps construction from non-minimal import.
            for e in effects:
                path = str(e.get("path", ""))
                if e.get("kind") == "fs_mkdir" and (
                    path.endswith("/bin") or "/bin/.deps" in path or path.endswith("/.deps")
                ):
                    # Under hermetic fan-in, installer construction must not run.
                    matched.append("fs_mkdir:installer_bin_deps")
                    break
        if path_delta:
            # Filter sandbox project bin injections that would come from installer.
            for p in path_delta:
                if "/bin" in p and SANDBOX in p:
                    matched.append(f"path_mutation:{p}")

        purity_passed = len(matched) == 0
        print("FACP022_CORE::" + json.dumps({
            "purity_passed": purity_passed,
            "matched_effects": matched,
            "before_env": before_env,
            "after_env": after_env,
            "path_delta": path_delta,
            "effect_kinds": sorted({e["kind"] for e in effects}),
            "fan_in_code": fan.code,
            "normalized_as_success": False,
            "disposition": "hermetic_core_import" if purity_passed else "impurity_observed",
        }, sort_keys=True))
        """
    )
    started = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(_WORKSPACE_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    assert completed.returncode == 0, (
        f"sandbox core import failed\nstdout={completed.stdout[-4000:]}\n"
        f"stderr={completed.stderr[-4000:]}"
    )
    line = next(
        ln for ln in completed.stdout.splitlines() if ln.startswith("FACP022_CORE::")
    )
    observation = json.loads(line[len("FACP022_CORE::") :])
    observation["elapsed_ms"] = round(elapsed_ms, 3)
    assert observation["purity_passed"] is True, observation
    assert observation["matched_effects"] == []
    assert observation["after_env"]["IPFS_DATASETS_AUTO_INSTALL"] != "true"
    assert observation["disposition"] == "hermetic_core_import"


def test_fan_in_preserves_unrelated_exports(tmp_path: Path):
    init = _load_initialization_module()

    class _FakePackage:
        __version__ = "0.2.0"
        unrelated_export = object()

        @staticmethod
        def _enable_default_auto_install() -> None:
            os.environ["IPFS_DATASETS_AUTO_INSTALL"] = "true"

    fake = _FakePackage()
    sentinel = fake.unrelated_export
    result = init.apply_package_root_fan_in(package_module=fake)
    assert result.ok
    assert result.details.get("unrelated_exports_preserved") is True
    assert fake.unrelated_export is sentinel
    assert fake.__version__ == "0.2.0"
    # Patched helper must not silently default on.
    for key in ("IPFS_DATASETS_AUTO_INSTALL", "IPFS_KIT_AUTO_INSTALL_DEPS"):
        os.environ.pop(key, None)
    fake._enable_default_auto_install()
    assert os.environ.get("IPFS_DATASETS_AUTO_INSTALL") not in {"true", "1"}


def test_outcome_dicts_never_label_failure_as_success(tmp_path: Path):
    init = _load_initialization_module()

    failed = init.initialize_datasets(authorize_install=True)
    payload = failed.to_dict()
    assert payload["ok"] is False
    assert payload["outcome"] in {"Unavailable", "Failed"}
    # Failure payloads must not carry forbidden success labels as outcome.
    assert payload["outcome"].lower() not in FORBIDDEN_SUCCESS_ON_FAILURE
