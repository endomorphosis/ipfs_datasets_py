"""Hermetic ordinary-import regression coverage for semantic-state (DSS-011).

Ordinary imports install nothing, access no network, start no process or thread,
write nothing, and mutate no environment under the standard opt-outs.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[5]
_OPT_OUTS = {
    "IPFS_DATASETS_AUTO_INSTALL": "0",
    "IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS": "0",
    "IPFS_DATASETS_PY_MINIMAL_IMPORTS": "1",
    "IPFS_KIT_AUTO_INSTALL_DEPS": "0",
    "PYTHONDONTWRITEBYTECODE": "1",
}

_PACKAGE = "ipfs_datasets_py.logic.software_contracts.semantic_state"


def _probe(action: str) -> subprocess.CompletedProcess[str]:
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
            effects.append("write:" + str(args[0]))
            raise AssertionError("forbidden import write")
    if event in {{
        "os.mkdir",
        "os.remove",
        "os.rmdir",
        "os.rename",
        "os.replace",
        "socket.connect",
        "subprocess.Popen",
    }}:
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
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def _assert_hermetic(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, (
        f"returncode={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert json.loads(result.stdout.splitlines()[-1]) == {"ok": True}


def test_semantic_state_package_import_is_hermetic_under_opt_outs() -> None:
    _assert_hermetic(
        _probe(f"import {_PACKAGE}\nassert {_PACKAGE}.__all__\n")
    )


def test_semantic_state_submodule_imports_are_hermetic_under_opt_outs() -> None:
    """Leaf modules used by the facade must also be side-effect free on import."""
    modules = (
        f"{_PACKAGE}.api",
        f"{_PACKAGE}.models",
        f"{_PACKAGE}.merkle",
        f"{_PACKAGE}.capsules",
        f"{_PACKAGE}.bindings",
        f"{_PACKAGE}.invalidation",
        f"{_PACKAGE}.freshness",
        f"{_PACKAGE}.source",
        f"{_PACKAGE}.test_selection",
        f"{_PACKAGE}.oracle",
    )
    action = "\n".join(f"import {name}" for name in modules) + "\n"
    _assert_hermetic(_probe(action))


def test_semantic_state_import_exposes_closed_facade_only() -> None:
    """Fresh process: package import yields the closed public surface."""
    action = f'''\
import {_PACKAGE} as pkg
required = {{
    "build_semantic_state",
    "verify_semantic_state_bundle",
    "open_semantic_state",
    "view_semantic_state_bundle",
    "select_tests_and_proofs",
    "compare_test_selection_oracle",
    "SemanticStateView",
    "SemanticStateBundle",
    "SemanticCapsule",
}}
missing = sorted(required - set(pkg.__all__))
assert not missing, missing
# No MCP++ wire types on the package.
for banned in (
    "InterfaceDescriptor",
    "ExecutionEnvelope",
    "ExecutionReceipt",
    "DAGEvent",
):
    assert banned not in pkg.__all__
    assert not hasattr(pkg, banned)
'''
    _assert_hermetic(_probe(action))
