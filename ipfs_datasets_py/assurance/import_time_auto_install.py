"""Fail-closed PCPR-010 Datasets import-time auto-install removal.

Package import must not set auto-install flags, construct
``DependencyInstaller``, mkdir project bin/deps, mutate PATH, invoke pip,
or bootstrap companion repositories. Installation remains an explicit CLI
or operator action. Missing optional dependencies stay typed unavailable.

This module is not release authority: it does not write DuckDB or Quack
state and never emits a closed PCPR release outcome. Live claims require
live evidence. Simulated results are not live.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import textwrap
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

INTERFACE: Final = "DatasetsImportTimeAutoInstallRemoval@1"
SCHEMA: Final = "ipfs_datasets_py/assurance/import-time-auto-install-removal@1"
VERDICT_SCHEMA: Final = (
    "ipfs_datasets_py/assurance/import-time-auto-install-removal-verdict@1"
)
PCPR_010_TASK_ID: Final = "PCPR-010"
PCPR_010_GOAL_ID: Final = "PCPR-G210"
PCPR_003_TASK_ID: Final = "PCPR-003"
PCPR_PROGRAM_ID: Final = "proof-carrying-platform-qualification-and-release-v1"
PCPR_BOARD_NAMESPACE: Final = "proof-carrying-platform-qualification-and-release-v1"
EVIDENCE_ID: Final = "pcpr/datasets-import-time-auto-install-removal@1"

CLOSED_RELEASE_OUTCOMES: Final[frozenset[str]] = frozenset(
    {
        "release_candidate_qualified",
        "non_promoted_supervisor_unqualified",
        "non_promoted_import_or_false_success",
        "non_promoted_live_storage_gap",
        "non_promoted_live_compute_gap",
        "non_promoted_solver_gap",
        "non_promoted_packaging_gap",
        "non_promoted_dependency_reproducibility",
        "non_promoted_security_failure",
        "non_promoted_interoperability_gap",
        "non_promoted_reference_workflow_failure",
        "non_promoted_unmeasured",
        "non_promoted_operator_gate_required",
    }
)
PROMOTION_STATUSES: Final[frozenset[str]] = frozenset(
    {
        "supervisor_promoted",
        "supervisor_non_promoted",
        "rnd_non_promoted",
        "typed_unavailable",
        "typed_blocked",
    }
)
EVIDENCE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "measured",
        "measured_live",
        "measured_hermetic",
        "estimated",
        "simulated",
        "unavailable",
    }
)

INIT_RELPATH: Final = "ipfs_datasets_py/__init__.py"
INSTALLER_RELPATH: Final = "ipfs_datasets_py/auto_installer.py"
ROUTER_RELPATH: Final = "ipfs_datasets_py/ipfs_backend_router.py"
ASSURANCE_INIT_RELPATH: Final = "ipfs_datasets_py/assurance/initialization.py"

AUTO_INSTALL_ENV_KEYS: Final[tuple[str, ...]] = (
    "IPFS_DATASETS_AUTO_INSTALL",
    "IPFS_KIT_AUTO_INSTALL_DEPS",
    "IPFS_AUTO_INSTALL",
)

HERMETIC_CANDIDATE_SUITES: Final[tuple[str, ...]] = (
    "tests/unit/test_pcpr_010_import_time_auto_install.py",
)

SEALED_PATH: Final = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
SEALED_PYTHON: Final = "/usr/bin/python3.12"


class ImportTimeAutoInstallError(Exception):
    """Fail-closed PCPR-010 contract error."""


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def content_identity(value: Any) -> str:
    """CIDv1 DAG-JSON/sha2-256 identity (baguqeera…)."""

    digest = hashlib.sha256(canonical_json_bytes(value)).digest()
    raw = b"\x01\xa9\x02\x12\x20" + digest
    return "b" + base64.b32encode(raw).decode("ascii").rstrip("=").lower()


def discover_datasets_root(start: Path | None = None) -> Path | None:
    here = Path(start or __file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "ipfs_datasets_py").is_dir() and (
            candidate / "pyproject.toml"
        ).is_file():
            return candidate
    return None


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ImportTimeAutoInstallError(f"{name} must be a non-empty string")
    return value.strip()


def _kind(value: Any, name: str) -> str:
    kind = _text(value, name)
    if kind not in EVIDENCE_KINDS:
        raise ImportTimeAutoInstallError(f"{name} is not an admitted evidence kind")
    return kind


def _reject_closed_release_value(value: Any, name: str) -> None:
    if isinstance(value, str) and value in CLOSED_RELEASE_OUTCOMES:
        raise ImportTimeAutoInstallError(
            f"{name} must not be a closed PCPR release outcome"
        )


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def _is_main_guard(node: ast.If) -> bool:
    test = node.test
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return False
    if not isinstance(test.ops[0], ast.Eq):
        return False
    parts: set[object] = set()
    if isinstance(test.left, ast.Name):
        parts.add(test.left.id)
    elif isinstance(test.left, ast.Constant):
        parts.add(test.left.value)
    for comparator in test.comparators:
        if isinstance(comparator, ast.Name):
            parts.add(comparator.id)
        elif isinstance(comparator, ast.Constant):
            parts.add(comparator.value)
    return parts == {"__name__", "__main__"}


def _iter_module_level_statements(tree: ast.AST) -> list[ast.AST]:
    out: list[ast.AST] = []
    stack: list[ast.AST] = list(getattr(tree, "body", ()))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(node, ast.If):
            if _is_main_guard(node):
                continue
            stack.extend(node.body)
            stack.extend(node.orelse)
            out.append(node)
            continue
        if isinstance(node, ast.Try):
            stack.extend(node.body)
            for handler in node.handlers:
                stack.extend(handler.body)
            stack.extend(node.orelse)
            stack.extend(node.finalbody)
            out.append(node)
            continue
        if isinstance(node, ast.With):
            stack.extend(node.body)
            out.append(node)
            continue
        out.append(node)
    return out


def _module_level_calls(source: str) -> frozenset[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for stmt in _iter_module_level_statements(tree):
        for node in ast.walk(stmt):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node.func)
            if name:
                names.add(name)
    return frozenset(names)


def _function_assigns_auto_install_env(source: str, function_name: str) -> bool:
    tree = ast.parse(source)
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name != function_name:
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Subscript):
                value = child.value
                slice_node = child.slice
                if (
                    isinstance(value, ast.Attribute)
                    and value.attr == "environ"
                    and isinstance(slice_node, ast.Constant)
                    and slice_node.value in AUTO_INSTALL_ENV_KEYS
                ):
                    return True
            if isinstance(child, ast.Call):
                func = child.func
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr in {"setdefault", "__setitem__"}
                    and child.args
                    and isinstance(child.args[0], ast.Constant)
                    and child.args[0].value in AUTO_INSTALL_ENV_KEYS
                ):
                    return True
        return False
    return False


def _function_returns_true_when_env_unset(source: str, function_name: str) -> bool:
    """True when the named function still treats unset env as authorized."""

    tree = ast.parse(source)
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name != function_name:
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Return):
                continue
            value = child.value
            if isinstance(value, ast.Constant) and value.value is True:
                # `if primary is None and secondary is None: return True`
                return True
        return False
    return False


@dataclass(frozen=True)
class ImportProbe:
    probe_id: str
    present: bool | None
    evidence_kind: str
    live: bool
    simulated_represented_as_live: bool
    reason: str
    details: Mapping[str, Any] = MappingProxyType({})

    def to_mapping(self) -> dict[str, Any]:
        return {
            "probe_id": self.probe_id,
            "present": self.present,
            "evidence_kind": self.evidence_kind,
            "live": self.live,
            "simulated_represented_as_live": self.simulated_represented_as_live,
            "reason": self.reason,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class ImportTimeAutoInstallVerdict:
    schema: str
    interface: str
    promotion_status: str
    supervisor_disposition: str
    closed_release_outcome: str | None
    release_claim: bool
    completion_authoritative: bool
    contracts_frozen: bool
    duckdb_or_quack_state_written: bool
    import_sets_auto_install_env: bool
    import_constructs_installer: bool
    import_invokes_repo_installer: bool
    router_defaults_auto_install_on: bool
    simulated_results_represented_as_live: bool
    live_solver_qualified: bool
    live_solver_evidence_kind: str
    this_task_created_competing_authority: bool
    probes: tuple[ImportProbe, ...]
    blockers: tuple[str, ...]
    verdict_cid: str

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "interface": self.interface,
            "verdict_cid": self.verdict_cid,
            "promotion_status": self.promotion_status,
            "supervisor_disposition": self.supervisor_disposition,
            "closed_release_outcome": self.closed_release_outcome,
            "release_claim": self.release_claim,
            "completion_authoritative": self.completion_authoritative,
            "contracts_frozen": self.contracts_frozen,
            "duckdb_or_quack_state_written": self.duckdb_or_quack_state_written,
            "import_sets_auto_install_env": self.import_sets_auto_install_env,
            "import_constructs_installer": self.import_constructs_installer,
            "import_invokes_repo_installer": self.import_invokes_repo_installer,
            "router_defaults_auto_install_on": self.router_defaults_auto_install_on,
            "simulated_results_represented_as_live": (
                self.simulated_results_represented_as_live
            ),
            "live_solver_qualified": self.live_solver_qualified,
            "live_solver_evidence_kind": self.live_solver_evidence_kind,
            "this_task_created_competing_authority": (
                self.this_task_created_competing_authority
            ),
            "blocker_count": len(self.blockers),
            "blockers": list(self.blockers),
            "evidence_kind": "measured",
        }


def current_head_static_probes(
    *,
    datasets_root: Path | None = None,
) -> tuple[ImportProbe, ...]:
    """Measured current-tree AST probes. Missing files stay typed unavailable."""

    root = datasets_root or discover_datasets_root()
    if root is None or not root.is_dir():
        return (
            ImportProbe(
                probe_id="datasets_source_tree",
                present=None,
                evidence_kind="unavailable",
                live=False,
                simulated_represented_as_live=False,
                reason=(
                    "Datasets source tree is not present and is not recorded as empty."
                ),
            ),
        )

    probes: list[ImportProbe] = []
    init_source = _read_source(root, INIT_RELPATH)
    installer_source = _read_source(root, INSTALLER_RELPATH)
    router_source = _read_source(root, ROUTER_RELPATH)

    if init_source is None:
        probes.append(
            ImportProbe(
                probe_id="package_init",
                present=None,
                evidence_kind="unavailable",
                live=False,
                simulated_represented_as_live=False,
                reason=f"{INIT_RELPATH} is missing and is not recorded as empty.",
            )
        )
        return tuple(probes)

    init_calls = _module_level_calls(init_source)
    enable_call = "_enable_default_auto_install" in init_calls
    get_installer_call = "get_installer" in init_calls
    repo_installer_call = "ensure_repo_installer_current" in init_calls
    enable_writes = _function_assigns_auto_install_env(
        init_source, "_enable_default_auto_install"
    )
    probes.append(
        ImportProbe(
            probe_id="package_init_enable_default_auto_install_call",
            present=enable_call,
            evidence_kind="measured",
            live=False,
            simulated_represented_as_live=False,
            reason=(
                "Package import does not call _enable_default_auto_install."
                if not enable_call
                else "Package import still calls _enable_default_auto_install."
            ),
            details={"relpath": INIT_RELPATH},
        )
    )
    probes.append(
        ImportProbe(
            probe_id="package_init_enable_default_auto_install_env_write",
            present=enable_writes,
            evidence_kind="measured",
            live=False,
            simulated_represented_as_live=False,
            reason=(
                "_enable_default_auto_install does not write auto-install env."
                if not enable_writes
                else "_enable_default_auto_install still writes auto-install env."
            ),
            details={"relpath": INIT_RELPATH},
        )
    )
    probes.append(
        ImportProbe(
            probe_id="package_init_get_installer_call",
            present=get_installer_call,
            evidence_kind="measured",
            live=False,
            simulated_represented_as_live=False,
            reason=(
                "Package import does not call get_installer()."
                if not get_installer_call
                else "Package import still constructs the installer."
            ),
            details={"relpath": INIT_RELPATH, "calls": sorted(init_calls)},
        )
    )
    probes.append(
        ImportProbe(
            probe_id="package_init_ensure_repo_installer_current_call",
            present=repo_installer_call,
            evidence_kind="measured",
            live=False,
            simulated_represented_as_live=False,
            reason=(
                "Package import does not call ensure_repo_installer_current()."
                if not repo_installer_call
                else "Package import still invokes the repo installer bootstrap."
            ),
            details={"relpath": INIT_RELPATH},
        )
    )

    if router_source is None:
        probes.append(
            ImportProbe(
                probe_id="router_auto_install_default",
                present=None,
                evidence_kind="unavailable",
                live=False,
                simulated_represented_as_live=False,
                reason=f"{ROUTER_RELPATH} is missing and is not recorded as empty.",
            )
        )
    else:
        router_default_on = _function_returns_true_when_env_unset(
            router_source, "_auto_install_enabled"
        )
        probes.append(
            ImportProbe(
                probe_id="router_auto_install_default",
                present=router_default_on,
                evidence_kind="measured",
                live=False,
                simulated_represented_as_live=False,
                reason=(
                    "Router auto-install is fail-closed when env is unset."
                    if not router_default_on
                    else "Router still treats unset auto-install env as enabled."
                ),
                details={"relpath": ROUTER_RELPATH},
            )
        )

    if installer_source is None:
        probes.append(
            ImportProbe(
                probe_id="auto_installer_module",
                present=None,
                evidence_kind="unavailable",
                live=False,
                simulated_represented_as_live=False,
                reason=f"{INSTALLER_RELPATH} is missing and is not recorded as empty.",
            )
        )
    else:
        installer_calls = _module_level_calls(installer_source)
        constructs = "DependencyInstaller" in installer_calls
        probes.append(
            ImportProbe(
                probe_id="auto_installer_module_level_construction",
                present=constructs,
                evidence_kind="measured",
                live=False,
                simulated_represented_as_live=False,
                reason=(
                    "auto_installer import does not construct DependencyInstaller."
                    if not constructs
                    else "auto_installer still constructs DependencyInstaller at import."
                ),
                details={"relpath": INSTALLER_RELPATH},
            )
        )

    probes.append(
        ImportProbe(
            probe_id="live_solver_qualification",
            present=None,
            evidence_kind="unavailable",
            live=False,
            simulated_represented_as_live=False,
            reason=(
                "This task does not qualify live solvers. Missing Z3/cvc5/Lean/Coq "
                "evidence stays typed unavailable and is not recorded as False or passing."
            ),
        )
    )
    return tuple(probes)


def _read_source(root: Path, relpath: str) -> str | None:
    path = root / relpath
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def probe_cold_import(
    *,
    datasets_root: Path | None = None,
    python_executable: str | None = None,
) -> dict[str, Any]:
    """Subprocess cold-import observation. Missing interpreter stays unavailable."""

    root = datasets_root or discover_datasets_root()
    if root is None:
        return {
            "status": "unavailable",
            "evidence_kind": "unavailable",
            "reason": "Datasets source tree is not present.",
            "live": False,
            "simulated_represented_as_live": False,
        }

    python = python_executable or sys.executable
    if not python:
        return {
            "status": "unavailable",
            "evidence_kind": "unavailable",
            "reason": "Python interpreter is not present.",
            "live": False,
            "simulated_represented_as_live": False,
        }

    sandbox = Path(tempfile.mkdtemp(prefix="pcpr010-"))
    script = textwrap.dedent(
        r"""
        import json
        import os
        import socket
        import subprocess
        import sys
        from pathlib import Path

        effects = []
        SANDBOX = os.environ["PCPR010_SANDBOX"]
        PACKAGE_ROOT = os.environ["PCPR010_PACKAGE_ROOT"]

        def _record(kind, **fields):
            effects.append({"kind": kind, **fields})

        def _deny_net(api, *a, **k):
            _record("network", api=api)
            raise OSError(f"PCPR-010 network denied: {api}")

        socket.create_connection = lambda *a, **k: _deny_net("create_connection", *a, **k)
        socket.getaddrinfo = lambda *a, **k: _deny_net("getaddrinfo", *a, **k)

        def _deny_run(*a, **k):
            cmd = a[0] if a else k.get("args")
            _record(
                "subprocess",
                cmd=[str(x) for x in cmd] if isinstance(cmd, (list, tuple)) else repr(cmd),
            )
            raise RuntimeError("PCPR-010 subprocess denied")

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
            raise OSError(f"PCPR-010 write denied: {path}")

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
            "IPFS_DATASETS_INSTALL_ON_IMPORT",
        ):
            os.environ.pop(key, None)

        sys.path.insert(0, PACKAGE_ROOT)
        before_env = {
            "IPFS_DATASETS_AUTO_INSTALL": os.environ.get("IPFS_DATASETS_AUTO_INSTALL"),
            "IPFS_KIT_AUTO_INSTALL_DEPS": os.environ.get("IPFS_KIT_AUTO_INSTALL_DEPS"),
            "IPFS_AUTO_INSTALL": os.environ.get("IPFS_AUTO_INSTALL"),
        }
        before_path = os.environ.get("PATH", "")
        import ipfs_datasets_py

        after_env = {
            "IPFS_DATASETS_AUTO_INSTALL": os.environ.get("IPFS_DATASETS_AUTO_INSTALL"),
            "IPFS_KIT_AUTO_INSTALL_DEPS": os.environ.get("IPFS_KIT_AUTO_INSTALL_DEPS"),
            "IPFS_AUTO_INSTALL": os.environ.get("IPFS_AUTO_INSTALL"),
        }
        after_path = os.environ.get("PATH", "")
        before_parts = before_path.split(os.pathsep) if before_path else []
        after_parts = after_path.split(os.pathsep) if after_path else []
        path_delta = [p for p in after_parts if p not in before_parts]
        installer = getattr(ipfs_datasets_py, "installer", None)
        auto_install = bool(getattr(installer, "auto_install", False))
        missing = ipfs_datasets_py.ensure_module(
            "pcpr010_missing_optional_module_xyz", required=False
        )
        mkdir_installer = [
            e
            for e in effects
            if e.get("kind") == "fs_mkdir"
            and (
                str(e.get("path", "")).endswith("/bin")
                or "/bin/.deps" in str(e.get("path", ""))
                or str(e.get("path", "")).endswith("/.deps")
            )
        ]
        payload = {
            "import_ok": True,
            "auto_install": auto_install,
            "before_env": before_env,
            "after_env": after_env,
            "path_delta": path_delta,
            "network_effects": [e for e in effects if e.get("kind") == "network"],
            "subprocess_effects": [e for e in effects if e.get("kind") == "subprocess"],
            "installer_mkdir": mkdir_installer,
            "missing_optional_module": missing,
            "inert_installer": type(installer).__name__ if installer is not None else None,
        }
        print("PCPR010::" + json.dumps(payload, sort_keys=True, default=str))
        """
    )
    env = dict(os.environ)
    for key in (
        "IPFS_DATASETS_AUTO_INSTALL",
        "IPFS_KIT_AUTO_INSTALL_DEPS",
        "IPFS_AUTO_INSTALL",
        "IPFS_DATASETS_ENSURE_INSTALLER",
        "IPFS_DATASETS_PY_MINIMAL_IMPORTS",
        "IPFS_DATASETS_PY_BENCHMARK",
        "IPFS_DATASETS_INSTALL_ON_IMPORT",
        "PYTHONSAFEPATH",
    ):
        env.pop(key, None)
    env["PCPR010_SANDBOX"] = str(sandbox)
    env["PCPR010_PACKAGE_ROOT"] = str(root)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(root), env.get("PYTHONPATH", "")) if part
    )
    completed = subprocess.run(
        [python, "-c", script],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if completed.returncode != 0:
        return {
            "status": "failed",
            "evidence_kind": "measured",
            "live": False,
            "simulated_represented_as_live": False,
            "exit_code": completed.returncode,
            "stdout_tail": completed.stdout[-2000:],
            "stderr_tail": completed.stderr[-2000:],
            "reason": "Cold import subprocess did not exit 0.",
        }
    line = next(
        (ln for ln in completed.stdout.splitlines() if ln.startswith("PCPR010::")),
        None,
    )
    if line is None:
        return {
            "status": "failed",
            "evidence_kind": "measured",
            "live": False,
            "simulated_represented_as_live": False,
            "reason": "Cold import subprocess emitted no PCPR010 observation.",
            "stdout_tail": completed.stdout[-2000:],
        }
    observation = json.loads(line[len("PCPR010::") :])
    env_mutated = any(
        observation.get("after_env", {}).get(key) in {"true", "1", "yes", "on"}
        for key in AUTO_INSTALL_ENV_KEYS
    )
    inert = (
        observation.get("import_ok") is True
        and observation.get("auto_install") is False
        and not env_mutated
        and not observation.get("path_delta")
        and not observation.get("network_effects")
        and not observation.get("subprocess_effects")
        and not observation.get("installer_mkdir")
        and observation.get("missing_optional_module") is None
    )
    observation.update(
        {
            "status": "observed",
            "evidence_kind": "measured",
            "live": False,
            "simulated_represented_as_live": False,
            "inert": inert,
            "env_mutated": env_mutated,
            "reason": (
                "Cold import is inert: no auto-install env write, installer "
                "construction, PATH mutation, network, or pip."
                if inert
                else "Cold import still exhibits auto-install or environment-repair effects."
            ),
        }
    )
    return observation


def qualify_import_time_auto_install_removal(
    probes: Sequence[ImportProbe],
    *,
    cold_import: Mapping[str, Any] | None = None,
) -> ImportTimeAutoInstallVerdict:
    if not probes:
        raise ImportTimeAutoInstallError("at least one probe is required")
    normalized: list[ImportProbe] = []
    blockers: list[str] = []
    for probe in probes:
        kind = _kind(probe.evidence_kind, "evidence_kind")
        if probe.live and kind != "measured_live":
            raise ImportTimeAutoInstallError(
                "live claims require measured_live evidence"
            )
        if probe.simulated_represented_as_live:
            raise ImportTimeAutoInstallError(
                "simulated results must not be represented as live"
            )
        normalized.append(probe)
        if probe.probe_id == "live_solver_qualification":
            continue
        if probe.present is True and probe.probe_id in {
            "package_init_enable_default_auto_install_call",
            "package_init_enable_default_auto_install_env_write",
            "package_init_get_installer_call",
            "package_init_ensure_repo_installer_current_call",
            "router_auto_install_default",
            "auto_installer_module_level_construction",
        }:
            blockers.append(probe.probe_id)
        if probe.present is None and probe.evidence_kind == "unavailable":
            if probe.probe_id == "datasets_source_tree":
                blockers.append(probe.probe_id)

    import_sets_env = any(
        p.probe_id == "package_init_enable_default_auto_install_env_write"
        and p.present is True
        for p in normalized
    )
    import_constructs = any(
        p.probe_id == "package_init_get_installer_call" and p.present is True
        for p in normalized
    )
    import_repo = any(
        p.probe_id == "package_init_ensure_repo_installer_current_call"
        and p.present is True
        for p in normalized
    )
    router_default_on = any(
        p.probe_id == "router_auto_install_default" and p.present is True
        for p in normalized
    )
    if cold_import is not None:
        if cold_import.get("inert") is False:
            blockers.append("cold_import_not_inert")
        if cold_import.get("env_mutated"):
            import_sets_env = True
        if cold_import.get("auto_install"):
            import_constructs = True

    promotion_status = "rnd_non_promoted"
    _reject_closed_release_value(promotion_status, "promotion_status")
    payload = {
        "schema": VERDICT_SCHEMA,
        "interface": INTERFACE,
        "task_id": PCPR_010_TASK_ID,
        "goal_id": PCPR_010_GOAL_ID,
        "promotion_status": promotion_status,
        "supervisor_disposition": "supervisor_non_promoted",
        "closed_release_outcome": None,
        "release_claim": False,
        "completion_authoritative": False,
        "contracts_frozen": False,
        "duckdb_or_quack_state_written": False,
        "import_sets_auto_install_env": import_sets_env,
        "import_constructs_installer": import_constructs,
        "import_invokes_repo_installer": import_repo,
        "router_defaults_auto_install_on": router_default_on,
        "simulated_results_represented_as_live": False,
        "live_solver_qualified": False,
        "live_solver_evidence_kind": "unavailable",
        "this_task_created_competing_authority": False,
        "probes": [item.to_mapping() for item in normalized],
        "blockers": list(dict.fromkeys(blockers)),
    }
    return ImportTimeAutoInstallVerdict(
        schema=VERDICT_SCHEMA,
        interface=INTERFACE,
        promotion_status=promotion_status,
        supervisor_disposition="supervisor_non_promoted",
        closed_release_outcome=None,
        release_claim=False,
        completion_authoritative=False,
        contracts_frozen=False,
        duckdb_or_quack_state_written=False,
        import_sets_auto_install_env=import_sets_env,
        import_constructs_installer=import_constructs,
        import_invokes_repo_installer=import_repo,
        router_defaults_auto_install_on=router_default_on,
        simulated_results_represented_as_live=False,
        live_solver_qualified=False,
        live_solver_evidence_kind="unavailable",
        this_task_created_competing_authority=False,
        probes=tuple(normalized),
        blockers=tuple(dict.fromkeys(blockers)),
        verdict_cid=content_identity(payload),
    )


def qualify_current_head_import_time_auto_install() -> ImportTimeAutoInstallVerdict:
    return qualify_import_time_auto_install_removal(current_head_static_probes())


# Pinned identity of the ordinary current-head static verdict. Drift means
# the default payload changed and the outer receipt must be regenerated.
CURRENT_HEAD_NON_PROMOTION_VERDICT_CID: Final = (
    "baguqeerajdxhdv4abibas7zoh33qy5uvxf6zkqp7puxe3r47mzsjykjxmpiq"
)


def pcpr_010_receipt_promotion(
    verdict: ImportTimeAutoInstallVerdict,
) -> dict[str, Any]:
    if verdict.closed_release_outcome is not None:
        raise ImportTimeAutoInstallError(
            "import-time auto-install removal must not mint a closed release outcome"
        )
    if verdict.release_claim:
        raise ImportTimeAutoInstallError(
            "import-time auto-install removal must not claim a PCPR release"
        )
    if verdict.completion_authoritative:
        raise ImportTimeAutoInstallError(
            "import-time auto-install removal completion is not authoritative"
        )
    if verdict.duckdb_or_quack_state_written:
        raise ImportTimeAutoInstallError(
            "import-time auto-install removal must not write DuckDB or Quack state"
        )
    if verdict.promotion_status in CLOSED_RELEASE_OUTCOMES:
        raise ImportTimeAutoInstallError(
            "promotion_status must not be a closed release outcome"
        )
    return verdict.to_mapping()


__all__ = [
    "CLOSED_RELEASE_OUTCOMES",
    "CURRENT_HEAD_NON_PROMOTION_VERDICT_CID",
    "EVIDENCE_ID",
    "HERMETIC_CANDIDATE_SUITES",
    "INTERFACE",
    "ImportProbe",
    "ImportTimeAutoInstallError",
    "ImportTimeAutoInstallVerdict",
    "PCPR_010_GOAL_ID",
    "PCPR_010_TASK_ID",
    "SCHEMA",
    "content_identity",
    "current_head_static_probes",
    "discover_datasets_root",
    "pcpr_010_receipt_promotion",
    "probe_cold_import",
    "qualify_current_head_import_time_auto_install",
    "qualify_import_time_auto_install_removal",
]
