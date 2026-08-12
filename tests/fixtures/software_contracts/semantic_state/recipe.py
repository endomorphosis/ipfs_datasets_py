"""Compact recipe for the controlled Python selection fixture.

All baseline paths and mutation cases are independently declared here.  Callers
materialize ordinary source trees; the sealed ISI scanner consumes those trees
without importing this package.  No ``.git``, state store, receipt, hand-built
dependency edge, or second benchmark corpus is checked in.
"""

from __future__ import annotations

from typing import Any, Mapping

# ---------------------------------------------------------------------------
# Baseline repository (runnable under Python 3.12 + pytest; stdlib only)
# ---------------------------------------------------------------------------

BASELINE_FILES: dict[str, str] = {
    "pytest.ini": """\
[pytest]
testpaths = tests
pythonpath = .
markers =
    slow: optional slow case
    integration: optional integration case
""",
    "requirements.txt": """\
# Hermetic controlled fixture: pytest is supplied by the host test runner.
# No third-party runtime packages are required or downloaded.
""",
    "policy.toml": """\
[selection]
mode = "strict"
allow_full_fallback = true
version = "1"
""",
    "interface.json": """\
{
  "name": "controlled.pkg.core",
  "version": "1.0.0",
  "exports": ["add", "scale", "Payload"]
}
""",
    "pkg/__init__.py": """\
\"\"\"Controlled fixture package (baseline).\"\"\"

from pkg.core import add, scale
from pkg.models import Payload

__all__ = ["add", "scale", "Payload"]
""",
    "pkg/core.py": """\
\"\"\"Local body and public signature targets.\"\"\"


def add(value: int) -> int:
    return value + 1


def scale(value: int) -> int:
    return value * 2


def stable_helper(value: int) -> int:
    return value
""",
    "pkg/models.py": """\
\"\"\"Dataclass/schema target.\"\"\"

from dataclasses import dataclass


@dataclass(frozen=True)
class Payload:
    name: str
    count: int = 0


def serialize(payload: Payload) -> dict[str, object]:
    return {"name": payload.name, "count": payload.count}


def deserialize(data: dict[str, object]) -> Payload:
    return Payload(name=str(data["name"]), count=int(data.get("count", 0)))
""",
    "pkg/callers.py": """\
\"\"\"Cross-module call graph.\"\"\"

from pkg.core import add, scale


def pipeline(value: int) -> int:
    return scale(add(value))


def only_add(value: int) -> int:
    return add(value)
""",
    "pkg/exceptions_mod.py": """\
\"\"\"Exception and recovery targets.\"\"\"


class ServiceError(ValueError):
    pass


def service(flag: str) -> str:
    if flag == "boom":
        raise ServiceError("baseline-failure")
    return flag


def recover(flag: str) -> str:
    try:
        return service(flag)
    except ServiceError:
        return "recovered"
""",
    "pkg/dynamic_mod.py": """\
\"\"\"Dynamic import boundary (intentionally conservative/opaque to static analysis).\"\"\"

import importlib


def load_extension(name: str):
    return importlib.import_module(name)


def invoke_extension(name: str, attr: str):
    module = load_extension(name)
    return getattr(module, attr)
""",
    "pkg/monkey_mod.py": """\
\"\"\"Monkey-patch surface used by the mutation case.\"\"\"


class Target:
    def method(self) -> int:
        return 1


def run() -> int:
    return Target().method()
""",
    "pkg/native_mod.py": """\
\"\"\"Opaque native-dependency boundary (no real extension required at runtime).\"\"\"

from __future__ import annotations

NATIVE_LIBRARY = "libcontrolled_fixture_native.so"


def native_scale(value: int) -> int:
    # Hermetic pure-Python stand-in.  The declared native library name is the
    # opaque boundary for selection/fallback tests; it is never loaded here.
    _ = NATIVE_LIBRARY
    return value * 3
""",
    "pkg/generated_reader.py": """\
\"\"\"Consumer of generated input files.\"\"\"

from __future__ import annotations

import json
from pathlib import Path

_GENERATED = Path(__file__).resolve().parent.parent / "generated" / "payload.json"


def read_generated() -> dict[str, object]:
    return json.loads(_GENERATED.read_text(encoding="utf-8"))
""",
    "generated/payload.json": """\
{
  "kind": "baseline",
  "value": 7
}
""",
    "plugins/sample_plugin.py": """\
\"\"\"Optional pytest-style plugin module (ordinary importable file).\"\"\"

PLUGIN_ID = "sample-plugin-v1"


def plugin_hook() -> str:
    return PLUGIN_ID
""",
    "tests/conftest.py": """\
import pytest


@pytest.fixture
def database() -> str:
    return "baseline-db"


@pytest.fixture
def multiplier() -> int:
    return 2
""",
    "tests/test_core.py": """\
from pkg.core import add, scale, stable_helper


def test_add() -> None:
    assert add(1) == 2


def test_scale() -> None:
    assert scale(3) == 6


def test_stable_helper() -> None:
    assert stable_helper(9) == 9
""",
    "tests/test_models.py": """\
from pkg.models import Payload, deserialize, serialize


def test_payload_roundtrip() -> None:
    payload = Payload(name="alpha", count=1)
    assert deserialize(serialize(payload)) == payload


def test_payload_defaults() -> None:
    assert Payload(name="beta").count == 0
""",
    "tests/test_callers.py": """\
from pkg.callers import only_add, pipeline


def test_pipeline() -> None:
    assert pipeline(1) == 4


def test_only_add() -> None:
    assert only_add(4) == 5
""",
    "tests/test_exceptions.py": """\
from pkg.exceptions_mod import recover, service


def test_service_ok() -> None:
    assert service("ok") == "ok"


def test_recover() -> None:
    assert recover("boom") == "recovered"
""",
    "tests/test_fixture_dep.py": """\
def test_database_name(database: str) -> None:
    assert database == "baseline-db"


def test_multiplier(multiplier: int) -> None:
    assert multiplier == 2
""",
    "tests/test_dynamic.py": """\
from pkg import core
from pkg.dynamic_mod import invoke_extension


def test_invoke_extension() -> None:
    assert invoke_extension("pkg.core", "add")(1) == core.add(1)
""",
    "tests/test_monkey.py": """\
from pkg.monkey_mod import run


def test_run() -> None:
    assert run() == 1
""",
    "tests/test_native.py": """\
from pkg.native_mod import native_scale


def test_native_scale() -> None:
    assert native_scale(2) == 6
""",
    "tests/test_generated.py": """\
from pkg.generated_reader import read_generated


def test_read_generated() -> None:
    data = read_generated()
    assert data["kind"] == "baseline"
    assert data["value"] == 7
""",
    "tests/test_plugin.py": """\
from plugins.sample_plugin import plugin_hook


def test_plugin_hook() -> None:
    assert plugin_hook() == "sample-plugin-v1"
""",
    "tests/test_policy_interface.py": """\
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_policy_version() -> None:
    text = (ROOT / "policy.toml").read_text(encoding="utf-8")
    assert 'version = "1"' in text


def test_interface_version() -> None:
    text = (ROOT / "interface.json").read_text(encoding="utf-8")
    assert '"version": "1.0.0"' in text
""",
    "proofs/core_add.proof": """\
# Synthetic proof obligation identity (not executed).
obligation: pkg.core.add
status: baseline
""",
}

# Deterministic pytest node IDs for the baseline universe (authoritative domain).
BASELINE_TEST_NODE_IDS: tuple[str, ...] = (
    "tests/test_callers.py::test_only_add",
    "tests/test_callers.py::test_pipeline",
    "tests/test_core.py::test_add",
    "tests/test_core.py::test_scale",
    "tests/test_core.py::test_stable_helper",
    "tests/test_dynamic.py::test_invoke_extension",
    "tests/test_exceptions.py::test_recover",
    "tests/test_exceptions.py::test_service_ok",
    "tests/test_fixture_dep.py::test_database_name",
    "tests/test_fixture_dep.py::test_multiplier",
    "tests/test_generated.py::test_read_generated",
    "tests/test_models.py::test_payload_defaults",
    "tests/test_models.py::test_payload_roundtrip",
    "tests/test_monkey.py::test_run",
    "tests/test_native.py::test_native_scale",
    "tests/test_plugin.py::test_plugin_hook",
    "tests/test_policy_interface.py::test_interface_version",
    "tests/test_policy_interface.py::test_policy_version",
)

BASELINE_PROOF_IDS: tuple[str, ...] = ("proofs/core_add.proof",)


def _write(path: str, content: str) -> dict[str, str]:
    return {"op": "write", "path": path, "content": content}


def _delete(path: str) -> dict[str, str]:
    return {"op": "delete", "path": path}


def _rename(source: str, dest: str) -> dict[str, str]:
    return {"op": "rename", "from": source, "to": dest}


# ---------------------------------------------------------------------------
# Independently declared mutation cases
# ---------------------------------------------------------------------------
# Each case owns: kind, changed_paths, file_ops, authored oracles, and ordinary
# expectation flags.  Formatting truth uses an empty affected-test oracle and
# semantic_change=false — never an analyzer-bypass flag.

MUTATION_CASES: tuple[dict[str, Any], ...] = (
    {
        "case_id": "local_body",
        "kind": "local_body",
        "description": "Local function body change of pkg.core.add.",
        "changed_paths": ("pkg/core.py",),
        "file_ops": (
            _write(
                "pkg/core.py",
                '''\
"""Local body and public signature targets."""


def add(value: int) -> int:
    return value + 2


def scale(value: int) -> int:
    return value * 2


def stable_helper(value: int) -> int:
    return value
''',
            ),
        ),
        "affected_tests": (
            "tests/test_callers.py::test_only_add",
            "tests/test_callers.py::test_pipeline",
            "tests/test_core.py::test_add",
            "tests/test_dynamic.py::test_invoke_extension",
        ),
        "affected_proofs": ("proofs/core_add.proof",),
        "semantic_change": True,
        "requires_full_fallback": False,
        "formatting_only": False,
    },
    {
        "case_id": "signature",
        "kind": "signature",
        "description": "Public signature change of pkg.core.scale.",
        "changed_paths": ("pkg/core.py",),
        "file_ops": (
            _write(
                "pkg/core.py",
                '''\
"""Local body and public signature targets."""


def add(value: int) -> int:
    return value + 1


def scale(value: int, factor: int = 2) -> int:
    return value * factor


def stable_helper(value: int) -> int:
    return value
''',
            ),
        ),
        "affected_tests": (
            "tests/test_callers.py::test_pipeline",
            "tests/test_core.py::test_scale",
        ),
        "affected_proofs": (),
        "semantic_change": True,
        "requires_full_fallback": False,
        "formatting_only": False,
    },
    {
        "case_id": "cross_module",
        "kind": "cross_module",
        "description": "Cross-module caller body change.",
        "changed_paths": ("pkg/callers.py",),
        "file_ops": (
            _write(
                "pkg/callers.py",
                '''\
"""Cross-module call graph."""

from pkg.core import add, scale


def pipeline(value: int) -> int:
    return scale(add(value)) + 1


def only_add(value: int) -> int:
    return add(value)
''',
            ),
        ),
        "affected_tests": ("tests/test_callers.py::test_pipeline",),
        "affected_proofs": (),
        "semantic_change": True,
        "requires_full_fallback": False,
        "formatting_only": False,
    },
    {
        "case_id": "schema",
        "kind": "schema",
        "description": "Dataclass/schema field addition on Payload.",
        "changed_paths": ("pkg/models.py",),
        "file_ops": (
            _write(
                "pkg/models.py",
                '''\
"""Dataclass/schema target."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Payload:
    name: str
    count: int = 0
    enabled: bool = False


def serialize(payload: Payload) -> dict[str, object]:
    return {
        "name": payload.name,
        "count": payload.count,
        "enabled": payload.enabled,
    }


def deserialize(data: dict[str, object]) -> Payload:
    return Payload(
        name=str(data["name"]),
        count=int(data.get("count", 0)),
        enabled=bool(data.get("enabled", False)),
    )
''',
            ),
        ),
        "affected_tests": (
            "tests/test_models.py::test_payload_defaults",
            "tests/test_models.py::test_payload_roundtrip",
        ),
        "affected_proofs": (),
        "semantic_change": True,
        "requires_full_fallback": False,
        "formatting_only": False,
    },
    {
        "case_id": "exception",
        "kind": "exception",
        "description": "Raised exception type change with stale recovery.",
        "changed_paths": ("pkg/exceptions_mod.py",),
        "file_ops": (
            _write(
                "pkg/exceptions_mod.py",
                '''\
"""Exception and recovery targets."""


class ServiceError(ValueError):
    pass


class ServiceBoom(RuntimeError):
    pass


def service(flag: str) -> str:
    if flag == "boom":
        raise ServiceBoom("mutated-failure")
    return flag


def recover(flag: str) -> str:
    try:
        return service(flag)
    except ServiceError:
        return "recovered"
''',
            ),
        ),
        "affected_tests": (
            "tests/test_exceptions.py::test_recover",
            "tests/test_exceptions.py::test_service_ok",
        ),
        "affected_proofs": (),
        "semantic_change": True,
        "requires_full_fallback": False,
        "formatting_only": False,
    },
    {
        "case_id": "fixture",
        "kind": "fixture",
        "description": "Pytest fixture body change for database.",
        "changed_paths": ("tests/conftest.py",),
        "file_ops": (
            _write(
                "tests/conftest.py",
                '''\
import pytest


@pytest.fixture
def database() -> str:
    return "mutated-db"


@pytest.fixture
def multiplier() -> int:
    return 2
''',
            ),
        ),
        "affected_tests": ("tests/test_fixture_dep.py::test_database_name",),
        "affected_proofs": (),
        "semantic_change": True,
        "requires_full_fallback": False,
        "formatting_only": False,
    },
    {
        "case_id": "config",
        "kind": "config",
        "description": "Pytest configuration marker change.",
        "changed_paths": ("pytest.ini",),
        "file_ops": (
            _write(
                "pytest.ini",
                """\
[pytest]
testpaths = tests
pythonpath = .
markers =
    slow: optional slow case
    integration: optional integration case
    controlled: controlled fixture marker
""",
            ),
        ),
        "affected_tests": BASELINE_TEST_NODE_IDS,
        "affected_proofs": (),
        "semantic_change": True,
        "requires_full_fallback": False,
        "formatting_only": False,
    },
    {
        "case_id": "plugin",
        "kind": "plugin",
        "description": "Plugin module identity change.",
        "changed_paths": ("plugins/sample_plugin.py",),
        "file_ops": (
            _write(
                "plugins/sample_plugin.py",
                '''\
"""Optional pytest-style plugin module (ordinary importable file)."""

PLUGIN_ID = "sample-plugin-v2"


def plugin_hook() -> str:
    return PLUGIN_ID
''',
            ),
        ),
        "affected_tests": ("tests/test_plugin.py::test_plugin_hook",),
        "affected_proofs": (),
        "semantic_change": True,
        "requires_full_fallback": False,
        "formatting_only": False,
    },
    {
        "case_id": "lock",
        "kind": "lock",
        "description": "Lock/environment requirements pin change.",
        "changed_paths": ("requirements.txt",),
        "file_ops": (
            _write(
                "requirements.txt",
                """\
# Hermetic controlled fixture: pytest is supplied by the host test runner.
# Environment pin changed for lock invalidation (not installed by the fixture).
# pin: controlled-fixture-env==2.0.0
""",
            ),
        ),
        "affected_tests": BASELINE_TEST_NODE_IDS,
        "affected_proofs": BASELINE_PROOF_IDS,
        "semantic_change": True,
        "requires_full_fallback": False,
        "formatting_only": False,
    },
    {
        "case_id": "policy",
        "kind": "policy",
        "description": "Selection policy version change.",
        "changed_paths": ("policy.toml",),
        "file_ops": (
            _write(
                "policy.toml",
                """\
[selection]
mode = "strict"
allow_full_fallback = true
version = "2"
""",
            ),
        ),
        "affected_tests": ("tests/test_policy_interface.py::test_policy_version",),
        "affected_proofs": (),
        "semantic_change": True,
        "requires_full_fallback": False,
        "formatting_only": False,
    },
    {
        "case_id": "interface",
        "kind": "interface",
        "description": "Public interface descriptor version change.",
        "changed_paths": ("interface.json",),
        "file_ops": (
            _write(
                "interface.json",
                """\
{
  "name": "controlled.pkg.core",
  "version": "1.1.0",
  "exports": ["add", "scale", "Payload"]
}
""",
            ),
        ),
        "affected_tests": ("tests/test_policy_interface.py::test_interface_version",),
        "affected_proofs": (),
        "semantic_change": True,
        "requires_full_fallback": False,
        "formatting_only": False,
    },
    {
        "case_id": "generated",
        "kind": "generated",
        "description": "Generated input file content change.",
        "changed_paths": ("generated/payload.json",),
        "file_ops": (
            _write(
                "generated/payload.json",
                """\
{
  "kind": "mutated",
  "value": 11
}
""",
            ),
        ),
        "affected_tests": ("tests/test_generated.py::test_read_generated",),
        "affected_proofs": (),
        "semantic_change": True,
        "requires_full_fallback": False,
        "formatting_only": False,
    },
    {
        "case_id": "dynamic",
        "kind": "dynamic",
        "description": "Dynamic import helper change (opaque reachability).",
        "changed_paths": ("pkg/dynamic_mod.py",),
        "file_ops": (
            _write(
                "pkg/dynamic_mod.py",
                '''\
"""Dynamic import boundary (intentionally conservative/opaque to static analysis)."""

import importlib


def load_extension(name: str):
    return importlib.import_module(name)


def invoke_extension(name: str, attr: str):
    module = load_extension(name)
    target = getattr(module, attr)
    return target
''',
            ),
        ),
        "affected_tests": ("tests/test_dynamic.py::test_invoke_extension",),
        "affected_proofs": (),
        "semantic_change": True,
        "requires_full_fallback": True,
        "formatting_only": False,
    },
    {
        "case_id": "monkey",
        "kind": "monkey",
        "description": "Monkey-patch assignment after class definition.",
        "changed_paths": ("pkg/monkey_mod.py",),
        "file_ops": (
            _write(
                "pkg/monkey_mod.py",
                '''\
"""Monkey-patch surface used by the mutation case."""


class Target:
    def method(self) -> int:
        return 1


Target.method = lambda self: 2  # type: ignore[method-assign]


def run() -> int:
    return Target().method()
''',
            ),
        ),
        "affected_tests": ("tests/test_monkey.py::test_run",),
        "affected_proofs": (),
        "semantic_change": True,
        "requires_full_fallback": True,
        "formatting_only": False,
    },
    {
        "case_id": "native",
        "kind": "native",
        "description": "Opaque native library identity change.",
        "changed_paths": ("pkg/native_mod.py",),
        "file_ops": (
            _write(
                "pkg/native_mod.py",
                '''\
"""Opaque native-dependency boundary (no real extension required at runtime)."""

from __future__ import annotations

NATIVE_LIBRARY = "libcontrolled_fixture_native_v2.so"


def native_scale(value: int) -> int:
    _ = NATIVE_LIBRARY
    return value * 4
''',
            ),
        ),
        "affected_tests": ("tests/test_native.py::test_native_scale",),
        "affected_proofs": (),
        "semantic_change": True,
        "requires_full_fallback": True,
        "formatting_only": False,
    },
    {
        "case_id": "format",
        "kind": "format",
        "description": (
            "Unrelated formatting-only whitespace/indent change. "
            "Authored oracle is empty: no tests are semantically affected. "
            "This is ordinary selection truth, not an analyzer bypass."
        ),
        "changed_paths": ("pkg/core.py",),
        "file_ops": (
            _write(
                "pkg/core.py",
                '''\

def add(value: int) -> int:
\treturn value + 1


def scale(value: int) -> int:
\treturn value * 2


def stable_helper(value: int) -> int:
\treturn value
''',
            ),
        ),
        # Empty oracle is intentional truth for a formatting-only mutation.
        "affected_tests": (),
        "affected_proofs": (),
        "semantic_change": False,
        "requires_full_fallback": False,
        "formatting_only": True,
    },
    {
        "case_id": "delete",
        "kind": "delete",
        "description": "Delete stable_helper and its dedicated test.",
        "changed_paths": ("pkg/core.py", "tests/test_core.py"),
        "file_ops": (
            _write(
                "pkg/core.py",
                '''\
"""Local body and public signature targets."""


def add(value: int) -> int:
    return value + 1


def scale(value: int) -> int:
    return value * 2
''',
            ),
            _write(
                "tests/test_core.py",
                '''\
from pkg.core import add, scale


def test_add() -> None:
    assert add(1) == 2


def test_scale() -> None:
    assert scale(3) == 6
''',
            ),
        ),
        "affected_tests": ("tests/test_core.py::test_stable_helper",),
        "affected_proofs": (),
        "semantic_change": True,
        "requires_full_fallback": False,
        "formatting_only": False,
        "deleted_symbols": ("pkg.core.stable_helper",),
        "deleted_tests": ("tests/test_core.py::test_stable_helper",),
    },
    {
        "case_id": "rename",
        "kind": "rename",
        "description": "Rename pkg/callers.py to pkg/pipeline_mod.py (heuristic rename).",
        "changed_paths": ("pkg/callers.py", "pkg/pipeline_mod.py", "tests/test_callers.py"),
        "file_ops": (
            _rename("pkg/callers.py", "pkg/pipeline_mod.py"),
            _write(
                "tests/test_callers.py",
                '''\
from pkg.pipeline_mod import only_add, pipeline


def test_pipeline() -> None:
    assert pipeline(1) == 4


def test_only_add() -> None:
    assert only_add(4) == 5
''',
            ),
        ),
        "affected_tests": (
            "tests/test_callers.py::test_only_add",
            "tests/test_callers.py::test_pipeline",
        ),
        "affected_proofs": (),
        "semantic_change": True,
        "requires_full_fallback": False,
        "formatting_only": False,
        "rename_pairs": (("pkg/callers.py", "pkg/pipeline_mod.py"),),
    },
)


def case_by_id() -> Mapping[str, Mapping[str, Any]]:
    return {str(case["case_id"]): case for case in MUTATION_CASES}


REQUIRED_MUTATION_KINDS: tuple[str, ...] = (
    "local_body",
    "signature",
    "cross_module",
    "schema",
    "exception",
    "fixture",
    "config",
    "plugin",
    "lock",
    "policy",
    "interface",
    "generated",
    "dynamic",
    "monkey",
    "native",
    "format",
    "delete",
    "rename",
)

# Fields that must never appear on any case declaration.
FORBIDDEN_CASE_FIELDS: frozenset[str] = frozenset(
    {
        "analyzer_bypass",
        "skip_analyzer",
        "special_bypass",
        "formatting_bypass",
        "ignore_analyzer",
    }
)
