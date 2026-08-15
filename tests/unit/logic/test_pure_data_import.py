"""LPC-061: pure-data imports stay side-effect free.

Acceptance (todo board LPC-061):

Importing contracts, catalog, syntax, formalization, provider protocol, and
supervisor adapter does not import solvers, install packages, open the network,
start processes, mutate files, probe hardware, or change environment variables.

Each target is imported in a fresh interpreter with audit hooks and opt-outs
that turn prohibited effects into hard failures.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Final


# test file: <repo>/ipfs_datasets_py/tests/unit/logic/test_pure_data_import.py
_TEST_FILE = Path(__file__).resolve()
_DATASETS_ROOT = _TEST_FILE.parents[3]  # .../ipfs_datasets_py (outer package dir)
_WORKSPACE_ROOT = _TEST_FILE.parents[4]  # monorepo / worktree root

_OPT_OUTS: Final[dict[str, str]] = {
    "IPFS_DATASETS_AUTO_INSTALL": "0",
    "IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS": "0",
    "IPFS_DATASETS_PY_MINIMAL_IMPORTS": "1",
    "IPFS_KIT_AUTO_INSTALL_DEPS": "0",
    "PYTHONDONTWRITEBYTECODE": "1",
}

# Closed pure-data import inventory (LPC-061 / notes/pure_data_imports.md).
PURE_DATA_MODULES: Final[dict[str, str]] = {
    "contracts": "ipfs_datasets_py.logic.syntax_core.contracts",
    "catalog": "ipfs_datasets_py.logic.families.canonical_catalog",
    "syntax": "ipfs_datasets_py.logic.syntax_core",
    "formalization": "ipfs_datasets_py.logic.formalization",
    "provider_protocol": "ipfs_datasets_py.logic.backends.protocol_v2",
    "provider_protocol_v1": "ipfs_datasets_py.logic.backends.provider",
    "provider_protocol_v1_adapter": (
        "ipfs_datasets_py.logic.backends.protocol_v1_adapter"
    ),
    "verification_api_contracts": "ipfs_datasets_py.logic.verification_api",
    "platform_manifest": "ipfs_datasets_py.logic.platform.manifest",
    "supervisor_adapter": (
        "ipfs_accelerate_py.agent_supervisor.proof.canonical_logic_adapter"
    ),
    "supervisor_provider_facade": (
        "ipfs_accelerate_py.agent_supervisor.proof.logic_provider_contract"
    ),
}

# Modules that must remain unloaded after a pure-data import.
FORBIDDEN_SOLVER_MODULES: Final[tuple[str, ...]] = (
    "z3",
    "z3py",
    "cvc5",
    "pysmt",
    "pysmt.shortcuts",
)

FORBIDDEN_INSTALLER_MODULES: Final[tuple[str, ...]] = (
    "pip",
    "pip._internal",
    "ensurepip",
    "ipfs_datasets_py.logic.backends.installers.registry",
    "ipfs_datasets_py.logic.external_provers.lazy_installer",
    "ipfs_datasets_py.logic.backends.z3.compiler",
    "ipfs_datasets_py.logic.backends.cvc5.compiler",
)

FORBIDDEN_HARDWARE_MODULES: Final[tuple[str, ...]] = (
    "psutil",
    "pynvml",
    "py3nvml",
    "GPUtil",
    "cpuinfo",
    "pyamdgpuinfo",
)

# Identity markers that must resolve after import (proves we loaded the right surface).
MODULE_MARKERS: Final[dict[str, str]] = {
    "contracts": "LOGIC_TOKEN_INTERFACE",
    "catalog": "CANONICAL_CATALOG_SNAPSHOT_INTERFACE",
    "syntax": "LOGIC_SYNTAX_CORE_INTERFACE",
    "formalization": "__all__",
    "provider_protocol": "LOGIC_PROVIDER_PROTOCOL_V2_INTERFACE",
    "provider_protocol_v1": "LOGIC_PROVIDER_PROTOCOL_VERSION",
    "provider_protocol_v1_adapter": "PROTOCOL_V1_ADAPTER_INTERFACE",
    "verification_api_contracts": "LOGIC_VERIFICATION_API_INTERFACE",
    "platform_manifest": "LOGIC_PLATFORM_MANIFEST_INTERFACE",
    "supervisor_adapter": "SUPERVISOR_CANONICAL_LOGIC_ADAPTER_INTERFACE",
    "supervisor_provider_facade": "CANONICAL_LOGIC_PROVIDER_MODULE",
}


def _pythonpath() -> str:
    parts = [
        str(_WORKSPACE_ROOT),
        str(_DATASETS_ROOT),
        os.environ.get("PYTHONPATH", ""),
    ]
    return os.pathsep.join(part for part in parts if part)


def _probe(action: str, *, timeout: float = 120.0) -> subprocess.CompletedProcess[str]:
    """Import in a fresh process that turns prohibited effects into failures."""
    script = f'''\
import json
import os
import sys
import threading

before = dict(os.environ)
effects = []

def forbidden(name):
    def call(*args, **kwargs):
        effects.append(name)
        raise AssertionError(f"forbidden import side effect: {{name}}")
    return call

os.system = forbidden("os.system")
for name in ("posix_spawn", "posix_spawnp", "spawnv", "spawnve", "spawnvp", "spawnvpe"):
    if hasattr(os, name):
        setattr(os, name, forbidden("os." + name))

_orig_thread_start = threading.Thread.start

def _thread_start(self, *args, **kwargs):
    effects.append("threading.Thread.start")
    raise AssertionError("forbidden import side effect: threading.Thread.start")

threading.Thread.start = _thread_start

def audit(event, args):
    if event == "open" and len(args) > 2:
        flags = args[2]
        if isinstance(flags, int) and flags & (
            os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
        ):
            path = str(args[0])
            # Bytecode and pytest cache writes are not production import effects.
            if path.endswith((".pyc", ".pyo")) or "__pycache__" in path:
                return
            if path.endswith((".coverage", ".pytest_cache")) or ".pytest_cache" in path:
                return
            effects.append("write:" + path)
            raise AssertionError("forbidden import write: " + path)
    if event in {{
        "os.mkdir",
        "os.remove",
        "os.rmdir",
        "os.rename",
        "os.replace",
        "socket.connect",
        "subprocess.Popen",
    }}:
        # Allow creating __pycache__ directories only (interpreter default).
        if event == "os.mkdir" and args and "__pycache__" in str(args[0]):
            return
        effects.append(event)
        raise AssertionError(f"forbidden import side effect: {{event}}")

sys.addaudithook(audit)
{action}
assert os.environ == before, "import changed environment variables"
assert not effects, effects
print(json.dumps({{"ok": True}}, sort_keys=True))
'''
    environment = dict(os.environ)
    environment.update(_OPT_OUTS)
    environment["PYTHONPATH"] = _pythonpath()
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(_WORKSPACE_ROOT),
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )


def _assert_hermetic(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, (
        f"returncode={result.returncode}\n"
        f"stdout={result.stdout}\n"
        f"stderr={result.stderr}"
    )
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines, f"empty stdout; stderr={result.stderr}"
    assert json.loads(lines[-1]) == {"ok": True}


def _import_action(role: str, module_name: str) -> str:
    marker = MODULE_MARKERS[role]
    forbidden = (
        FORBIDDEN_SOLVER_MODULES
        + FORBIDDEN_INSTALLER_MODULES
        + FORBIDDEN_HARDWARE_MODULES
    )
    forbidden_repr = repr(forbidden)
    # Supervisor adapter must not pull datasets at import time.
    datasets_guard = ""
    if role in {"supervisor_adapter", "supervisor_provider_facade"}:
        datasets_guard = """
assert not any(
    name == "ipfs_datasets_py" or name.startswith("ipfs_datasets_py.")
    for name in sys.modules
), "supervisor pure-data import must not load ipfs_datasets_py"
"""
    return f'''\
import importlib
import sys

mod = importlib.import_module({module_name!r})
marker = {marker!r}
module_name = {module_name!r}
assert hasattr(mod, marker), "missing marker %r on %r" % (marker, module_name)
loaded = set(sys.modules)
forbidden = {forbidden_repr}
offenders = sorted(name for name in forbidden if name in loaded)
assert not offenders, "forbidden modules loaded on import: %r" % (offenders,)
{datasets_guard}
'''


def test_pure_data_module_inventory_is_closed() -> None:
    """The closed inventory matches the LPC-061 acceptance surfaces."""
    required_roles = {
        "contracts",
        "catalog",
        "syntax",
        "formalization",
        "provider_protocol",
        "supervisor_adapter",
    }
    assert required_roles <= set(PURE_DATA_MODULES)
    assert set(MODULE_MARKERS) == set(PURE_DATA_MODULES)


def test_each_pure_data_import_is_hermetic() -> None:
    """Every pure-data module imports without prohibited side effects."""
    for role, module_name in PURE_DATA_MODULES.items():
        result = _probe(_import_action(role, module_name))
        try:
            _assert_hermetic(result)
        except AssertionError as exc:
            raise AssertionError(
                f"pure-data import failed for role={role!r} module={module_name!r}: {exc}"
            ) from exc


def test_combined_pure_data_imports_are_hermetic() -> None:
    """Importing the full pure-data set in one process stays side-effect free."""
    # Datasets pure-data first; supervisor adapters last (they must still not
    # force a datasets load of their own when imported alone — here datasets is
    # already present from earlier imports, which is fine for the combined check).
    datasets_roles = [
        role
        for role in PURE_DATA_MODULES
        if role not in {"supervisor_adapter", "supervisor_provider_facade"}
    ]
    supervisor_roles = ["supervisor_adapter", "supervisor_provider_facade"]
    lines = ["import importlib", "import sys", "loaded_roles = []"]
    for role in datasets_roles + supervisor_roles:
        module_name = PURE_DATA_MODULES[role]
        marker = MODULE_MARKERS[role]
        lines.append(f"mod = importlib.import_module({module_name!r})")
        lines.append(f"assert hasattr(mod, {marker!r})")
        lines.append(f"loaded_roles.append({role!r})")
    forbidden = (
        FORBIDDEN_SOLVER_MODULES
        + FORBIDDEN_INSTALLER_MODULES
        + FORBIDDEN_HARDWARE_MODULES
    )
    lines.append(f"forbidden = {forbidden!r}")
    lines.append(
        "offenders = sorted(name for name in forbidden if name in sys.modules)"
    )
    lines.append("assert not offenders, offenders")
    lines.append("assert set(loaded_roles) == set(" + repr(list(PURE_DATA_MODULES)) + ")")
    _assert_hermetic(_probe("\n".join(lines) + "\n"))


def test_supervisor_adapter_import_does_not_import_datasets() -> None:
    """Fresh process: supervisor adapter stays datasets-lazy on import."""
    action = _import_action(
        "supervisor_adapter",
        PURE_DATA_MODULES["supervisor_adapter"],
    )
    # Strengthen: also construct the default adapter without datasets.
    action += """
adapter = mod.SupervisorCanonicalLogicAdapter()
assert adapter.datasets_import_is_lazy() is True
assert not any(
    name == "ipfs_datasets_py" or name.startswith("ipfs_datasets_py.")
    for name in sys.modules
), "constructing the adapter must not import datasets"
"""
    _assert_hermetic(_probe(action))


def test_verification_api_import_does_not_load_install_or_solver_paths() -> None:
    """Public verification facade import stays free of install/solver graphs."""
    action = _import_action(
        "verification_api_contracts",
        PURE_DATA_MODULES["verification_api_contracts"],
    )
    action += """
assert "ipfs_datasets_py.logic.integration" not in sys.modules
assert "ipfs_datasets_py.logic.external_provers" not in sys.modules
assert mod.LOGIC_VERIFICATION_API_INTERFACE == "LogicVerificationAPI@1"
# Declarative discovery after import must not install or probe tools.
api = mod.get_verification_api()
features = api.list_features()
assert features is not None
assert features.status == mod.VerificationStatus.DECLARATIVE
assert "install_provider" in mod.STABLE_OPERATIONS
stable = mod.list_stable_features()
assert stable
# Install/solver graphs remain unloaded after declarative discovery.
assert "ipfs_datasets_py.logic.backends.installers.registry" not in sys.modules
assert "z3" not in sys.modules
assert "cvc5" not in sys.modules
"""
    _assert_hermetic(_probe(action))


def test_catalog_import_does_not_imply_executability() -> None:
    """Catalog snapshot import remains declarative and non-executable."""
    action = """
import importlib
import sys

mod = importlib.import_module(
    "ipfs_datasets_py.logic.families.canonical_catalog"
)
snapshot = mod.DEFAULT_CANONICAL_CATALOG_SNAPSHOT
assert snapshot is not None
assert mod.CANONICAL_CATALOG_SNAPSHOT_INTERFACE == "CanonicalLogicCatalogSnapshot@1"
# Safety floors: presence never upgrades to production admission / executability.
assert snapshot.presence_implies_executability() is False
assert snapshot.presence_implies_production_admission() is False
assert "z3" not in sys.modules
assert "cvc5" not in sys.modules
assert "pip" not in sys.modules
"""
    _assert_hermetic(_probe(action))


def test_provider_protocol_import_is_request_data_only() -> None:
    """Protocol@2 import exposes typed request vocabulary without runners."""
    action = """
import importlib
import sys

mod = importlib.import_module("ipfs_datasets_py.logic.backends.protocol_v2")
assert mod.LOGIC_PROVIDER_PROTOCOL_V2_INTERFACE == "LogicProviderProtocol@2"
assert "capability" in mod.PROTOCOL_V2_OPERATIONS
assert "prove" in mod.EXECUTABLE_OPERATIONS
# No process runner / solver backend on the import graph.
for banned in (
    "ipfs_datasets_py.logic.backends.process",
    "ipfs_datasets_py.logic.backends.z3.compiler",
    "ipfs_datasets_py.logic.backends.cvc5.compiler",
    "z3",
    "cvc5",
):
    assert banned not in sys.modules, banned
"""
    _assert_hermetic(_probe(action))
