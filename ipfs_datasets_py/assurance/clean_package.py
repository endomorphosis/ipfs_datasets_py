"""Fail-closed PCPR-050 Datasets clean package.

A clean Datasets install must not require sibling source trees, recursive
submodules, editable local dependencies, implicit sys.path injection,
import-time network, or mutable Git-branch release requires.

This module is not release authority: it does not write DuckDB or Quack
state and never emits a closed PCPR release outcome. Live claims require
live evidence. Simulated results are not live. Missing solvers stay typed
unavailable. Built wheel and sdist artifacts that are not present remain
typed unavailable and are not recorded as a published release.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import tomllib
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

INTERFACE: Final = "DatasetsCleanPackage@1"
SCHEMA: Final = "ipfs_datasets_py/assurance/clean-package@1"
VERDICT_SCHEMA: Final = (
    "ipfs_datasets_py/assurance/clean-package-verdict@1"
)
PCPR_050_TASK_ID: Final = "PCPR-050"
PCPR_050_GOAL_ID: Final = "PCPR-G600"
PCPR_043_TASK_ID: Final = "PCPR-043"
PCPR_017_TASK_ID: Final = "PCPR-017"
PCPR_016_TASK_ID: Final = "PCPR-016"
PCPR_001_TASK_ID: Final = "PCPR-001"
PCPR_PROGRAM_ID: Final = "proof-carrying-platform-qualification-and-release-v1"
PCPR_BOARD_NAMESPACE: Final = (
    "proof-carrying-platform-qualification-and-release-v1"
)
EVIDENCE_ID: Final = "pcpr/datasets-clean-package@1"

PACKAGE_NAME: Final = "ipfs_datasets_py"
PACKAGE_VERSION: Final = "0.2.0"
CANONICAL_PYTHON_REQUIRES: Final = ">=3.12"
CANONICAL_PYTHON_CLASSIFIER: Final = "Programming Language :: Python :: 3.12"
CANONICAL_LICENSE_CLASSIFIER: Final = (
    "License :: OSI Approved :: GNU Affero General Public License v3"
)
CANONICAL_SPDX: Final = "AGPL-3.0-only"

SIBLING_TREES: Final[tuple[str, ...]] = (
    "ipfs_kit_py",
    "ipfs_accelerate_py",
    ".tools",
)
MANIFEST_PRUNE_LINES: Final[tuple[str, ...]] = (
    "prune ipfs_kit_py",
    "prune ipfs_accelerate_py",
    "prune .tools",
)
SETUP_PACKAGE_EXCLUDES: Final[tuple[str, ...]] = (
    "ipfs_kit_py*",
    "ipfs_accelerate_py*",
)
PYPROJECT_CLEAN_PACKAGE_TABLE: Final = "tool.ipfs-datasets-py.clean-package"

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

HERMETIC_CANDIDATE_SUITES: Final[tuple[str, ...]] = (
    "tests/unit/test_pcpr_050_clean_package.py",
)

SEALED_PATH: Final = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
SEALED_PYTHON: Final = "/usr/bin/python3.12"

_VCS_REQUIREMENT_RE: Final = re.compile(
    r"""(?:^|[\s"'=,@])(?:git\+|hg\+|svn\+|bzr\+|file://)""",
    re.IGNORECASE,
)
_EDITABLE_REQUIREMENT_RE: Final = re.compile(
    r"""(?:^|[\s"'])(?:-e|--editable)\b""",
    re.IGNORECASE,
)
_PATH_DEP_RE: Final = re.compile(
    r"""(?:^|[\s"'=])(?:\.\./|\./|/home/|file://)""",
)
_SYS_PATH_RE: Final = re.compile(
    r"""sys\.path\.(?:insert|append|extend)\s*\(""",
)
_INSTALL_REQUIRES_RE: Final = re.compile(
    r"install_requires\s*=\s*(\[[^\]]*\])",
    re.DOTALL,
)
_PYTHON_REQUIRES_RE: Final = re.compile(
    r"""python_requires\s*=\s*['"]([^'"]+)['"]""",
)
_CLASSIFIER_RE: Final = re.compile(
    r"""['"](Programming Language :: Python :: [^'"]+)['"]"""
)
_SETUP_EXCLUDE_RE: Final = re.compile(
    r"""exclude\s*=\s*\[(.*?)\]""",
    re.DOTALL,
)
_CID_RE: Final = re.compile(r"^b[a-z2-7]+$")


class CleanPackageError(Exception):
    """Fail-closed PCPR-050 contract error."""


class CleanPackageAdmissionError(CleanPackageError):
    """Raised when a packaging input is rejected."""


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
        raise CleanPackageError(f"{name} must be a non-empty string")
    return value.strip()


def _kind(value: Any, name: str) -> str:
    kind = _text(value, name)
    if kind not in EVIDENCE_KINDS:
        raise CleanPackageError(f"{name} is not an admitted evidence kind")
    return kind


def _reject_closed_release_value(value: Any, name: str) -> None:
    if isinstance(value, str) and value in CLOSED_RELEASE_OUTCOMES:
        raise CleanPackageError(
            f"{name} must not be a closed PCPR release outcome"
        )


def clean_package_manifest() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "interface": INTERFACE,
        "package_name": PACKAGE_NAME,
        "package_version": PACKAGE_VERSION,
        "python_requires": CANONICAL_PYTHON_REQUIRES,
        "sibling_trees": list(SIBLING_TREES),
        "requires_sibling_source_trees": False,
        "requires_recursive_submodules": False,
        "editable_local_dependencies": False,
        "sys_path_injection": False,
        "import_network": False,
        "mutable_git_release_requires": False,
        "runtime_requires_authority": "setup.py:install_requires",
        "development_requirements_role": (
            "source-checkout-development-and-integration"
        ),
        "import_side_effects": "none",
        "task_id": PCPR_050_TASK_ID,
        "goal_id": PCPR_050_GOAL_ID,
    }


def scan_requirement_text(text: str) -> dict[str, tuple[str, ...]]:
    """Return forbidden requirement kinds found in a dependency document."""

    body = text or ""
    vcs = tuple(
        sorted({match.group(0).strip() for match in _VCS_REQUIREMENT_RE.finditer(body)})
    )
    editable = tuple(
        sorted(
            {
                match.group(0).strip()
                for match in _EDITABLE_REQUIREMENT_RE.finditer(body)
            }
        )
    )
    return {
        "vcs": vcs,
        "editable": editable,
    }


def parse_setup_install_requires(text: str) -> tuple[str, ...]:
    body = _text(text, "setup.py")
    match = _INSTALL_REQUIRES_RE.search(body)
    if match is None:
        raise CleanPackageError("setup.py install_requires is missing")
    try:
        parsed = ast.literal_eval(match.group(1))
    except (SyntaxError, ValueError) as exc:
        raise CleanPackageError("setup.py install_requires is not a literal") from exc
    if not isinstance(parsed, list):
        raise CleanPackageError("setup.py install_requires must be a list")
    return tuple(str(item) for item in parsed)


def parse_setup_python_requires(text: str) -> str:
    match = _PYTHON_REQUIRES_RE.search(_text(text, "setup.py"))
    if match is None:
        raise CleanPackageError("setup.py python_requires is missing")
    return match.group(1)


def parse_setup_python_classifiers(text: str) -> tuple[str, ...]:
    return tuple(_CLASSIFIER_RE.findall(_text(text, "setup.py")))


def parse_setup_package_excludes(text: str) -> tuple[str, ...]:
    body = _text(text, "setup.py")
    match = _SETUP_EXCLUDE_RE.search(body)
    if match is None:
        return ()
    raw = "[" + match.group(1) + "]"
    try:
        parsed = ast.literal_eval(raw)
    except (SyntaxError, ValueError):
        quoted = re.findall(r"""['"]([^'"]+)['"]""", match.group(1))
        return tuple(quoted)
    if not isinstance(parsed, list):
        return ()
    return tuple(str(item) for item in parsed)


def parse_pyproject_clean_package(text: str) -> dict[str, Any]:
    payload = tomllib.loads(_text(text, "pyproject.toml"))
    if not isinstance(payload, dict):
        raise CleanPackageError("pyproject.toml must be a table")
    project = payload.get("project")
    if not isinstance(project, dict):
        raise CleanPackageError("pyproject.toml [project] is required")
    requires_python = project.get("requires-python")
    classifiers = project.get("classifiers")
    project_classifiers = (
        tuple(str(item) for item in classifiers)
        if isinstance(classifiers, list)
        else ()
    )
    dependencies = project.get("dependencies")
    tool = payload.get("tool")
    clean: dict[str, Any] = {}
    find_exclude: tuple[str, ...] = ()
    if isinstance(tool, dict):
        datasets = tool.get("ipfs-datasets-py")
        if isinstance(datasets, dict):
            table = datasets.get("clean-package")
            if isinstance(table, dict):
                clean = dict(table)
        setuptools = tool.get("setuptools")
        if isinstance(setuptools, dict):
            packages = setuptools.get("packages")
            if isinstance(packages, dict):
                find = packages.get("find")
                if isinstance(find, dict):
                    raw_exclude = find.get("exclude")
                    if isinstance(raw_exclude, list):
                        find_exclude = tuple(str(item) for item in raw_exclude)
    return {
        "requires_python": requires_python,
        "classifiers": list(project_classifiers),
        "dependencies": dependencies,
        "clean_package": clean,
        "find_exclude": list(find_exclude),
    }


def parse_manifest_prunes(text: str) -> tuple[str, ...]:
    lines = []
    for raw in _text(text, "MANIFEST.in").splitlines():
        stripped = raw.strip()
        if stripped.startswith("prune "):
            lines.append(stripped)
    return tuple(lines)


def package_init_injects_sys_path(text: str) -> bool:
    return bool(_SYS_PATH_RE.search(_text(text, "__init__.py")))


REQUIRED_GOOD_PROBE_IDS: Final[frozenset[str]] = frozenset(
    {
        "install_requires_empty",
        "install_requires_has_no_vcs_url",
        "pyproject_has_no_static_dependencies",
        "python_requires_agrees",
        "python_classifier_agrees",
        "pyproject_python_classifier_agrees",
        "sibling_packages_excluded",
        "sibling_submodules_pruned",
        "pyproject_clean_package_table",
        "package_init_has_no_sys_path_injection",
        "requirements_txt_git_is_not_release_profile",
        "manifest_advertises_clean_package",
        "isolated_import_without_siblings",
    }
)
FORBIDDEN_PRESENT_PROBE_IDS: Final[frozenset[str]] = frozenset(
    {
        "mutable_git_release_requires",
        "editable_local_release_requires",
        "sibling_source_imported",
        "sys_path_injection_observed",
        "simulated_results_represented_as_live",
        "runtime_unavailable_represented_as_live",
        "built_wheel_represented_as_live",
        "built_sdist_represented_as_live",
        "published_release_represented_as_live",
    }
)


@dataclass(frozen=True)
class OutcomeProbe:
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
class CleanPackageVerdict:
    schema: str
    interface: str
    promotion_status: str
    supervisor_disposition: str
    closed_release_outcome: str | None
    release_claim: bool
    completion_authoritative: bool
    contracts_frozen: bool
    duckdb_or_quack_state_written: bool
    sibling_source_required: bool
    mutable_git_release_requires: bool
    isolated_import_without_siblings: bool
    simulated_results_represented_as_live: bool
    live_solver_qualified: bool
    live_solver_evidence_kind: str
    built_wheel_evidence_kind: str
    built_sdist_evidence_kind: str
    this_task_created_competing_authority: bool
    probes: tuple[OutcomeProbe, ...]
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
            "sibling_source_required": self.sibling_source_required,
            "mutable_git_release_requires": self.mutable_git_release_requires,
            "isolated_import_without_siblings": (
                self.isolated_import_without_siblings
            ),
            "simulated_results_represented_as_live": (
                self.simulated_results_represented_as_live
            ),
            "live_solver_qualified": self.live_solver_qualified,
            "live_solver_evidence_kind": self.live_solver_evidence_kind,
            "built_wheel_evidence_kind": self.built_wheel_evidence_kind,
            "built_sdist_evidence_kind": self.built_sdist_evidence_kind,
            "this_task_created_competing_authority": (
                self.this_task_created_competing_authority
            ),
            "blocker_count": len(self.blockers),
            "blockers": list(self.blockers),
            "evidence_kind": "measured",
        }


def _probe(
    probe_id: str,
    present: bool | None,
    *,
    reason: str,
    evidence_kind: str = "measured",
    live: bool = False,
    details: Mapping[str, Any] | None = None,
) -> OutcomeProbe:
    return OutcomeProbe(
        probe_id=probe_id,
        present=present,
        evidence_kind=evidence_kind,
        live=live,
        simulated_represented_as_live=False,
        reason=reason,
        details=MappingProxyType(dict(details or {})),
    )


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _which_sealed(name: str) -> str:
    env = {"PATH": SEALED_PATH, "HOME": "/tmp/ipfs-accelerate-validation-home-pcpr050"}
    path = shutil.which(name, path=SEALED_PATH)
    if not path:
        return "unavailable"
    resolved = Path(path)
    if not resolved.is_file():
        return "unavailable"
    return str(resolved)


def _sealed_python_module_origin(name: str) -> str:
    python = Path(SEALED_PYTHON)
    if not python.is_file():
        return "unavailable"
    script = (
        "import importlib.util, sys; "
        f"spec = importlib.util.find_spec({name!r}); "
        "print(spec.origin if spec is not None and spec.origin else 'unavailable')"
    )
    try:
        completed = subprocess.run(
            [str(python), "-c", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            env={
                "PATH": SEALED_PATH,
                "PYTHONNOUSERSITE": "1",
                "HOME": "/tmp/ipfs-accelerate-validation-home-pcpr050",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"
    origin = (completed.stdout or "").strip() or "unavailable"
    if origin == "unavailable" or "/home/" in origin or ".local" in origin:
        return "unavailable"
    return origin


def observe_sealed_validation_environment() -> dict[str, Any]:
    """Measure the sealed PATH; missing tools stay typed unavailable."""

    python3_12 = Path(SEALED_PYTHON)
    python_version = "unavailable"
    if python3_12.is_file():
        try:
            completed = subprocess.run(
                [str(python3_12), "--version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
                env={"PATH": SEALED_PATH, "PYTHONNOUSERSITE": "1"},
            )
            python_version = (
                completed.stdout or completed.stderr or ""
            ).strip() or "unavailable"
        except (OSError, subprocess.TimeoutExpired):
            python_version = "unavailable"
    pytest_origin = _sealed_python_module_origin("pytest")
    pytest_version = "unavailable"
    if pytest_origin != "unavailable":
        try:
            completed = subprocess.run(
                [
                    str(python3_12),
                    "-c",
                    "import pytest; print(pytest.__version__)",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
                env={"PATH": SEALED_PATH, "PYTHONNOUSERSITE": "1"},
            )
            pytest_version = (completed.stdout or "").strip() or "unavailable"
        except (OSError, subprocess.TimeoutExpired):
            pytest_version = "unavailable"
    return {
        "PATH": SEALED_PATH,
        "python_unqualified": _which_sealed("python"),
        "python3": _which_sealed("python3"),
        "python3_12": str(python3_12) if python3_12.is_file() else "unavailable",
        "python_version": python_version,
        "git_path": _which_sealed("git"),
        "pip_path": _which_sealed("pip"),
        "usr_bin_user_writable": os.access("/usr/bin", os.W_OK),
        "usr_local_bin_user_writable": os.access("/usr/local/bin", os.W_OK),
        "pytest_cli": _which_sealed("pytest"),
        "pytest_module": pytest_origin,
        "pytest_module_version": pytest_version,
        "setuptools_module": _sealed_python_module_origin("setuptools"),
        "wheel_module": _sealed_python_module_origin("wheel"),
        "build_module": _sealed_python_module_origin("build"),
        "pip_module": _sealed_python_module_origin("pip"),
        "duckdb": _which_sealed("duckdb"),
        "z3": _which_sealed("z3"),
        "cvc5": _which_sealed("cvc5"),
        "lean": _which_sealed("lean"),
        "coqtop": _which_sealed("coqtop"),
        "ipfs": _which_sealed("ipfs"),
        "nvcc": _which_sealed("nvcc"),
        "tsc": _which_sealed("tsc"),
        "node_path": _which_sealed("node"),
        "evidence_kind": "measured",
    }


def probe_isolated_import_without_siblings(
    root: Path,
    *,
    python_executable: str | None = None,
) -> dict[str, Any]:
    """Import Datasets from a sibling-free overlay. Not a live release."""

    python = python_executable or sys.executable
    if not python:
        return {
            "status": "unavailable",
            "evidence_kind": "unavailable",
            "import_ok": False,
            "sibling_source_imported": False,
            "reason": "Python interpreter is not present.",
        }
    overlay = Path(tempfile.mkdtemp(prefix="pcpr050-overlay-"))
    script = textwrap.dedent(
        r"""
        import json
        import os
        import socket
        import sys

        effects = []

        def _deny_net(api, *a, **k):
            effects.append({"kind": "network", "api": api})
            raise OSError(f"PCPR-050 network denied: {api}")

        socket.create_connection = lambda *a, **k: _deny_net("create_connection")
        socket.getaddrinfo = lambda *a, **k: _deny_net("getaddrinfo")

        overlay = os.environ["PCPR050_OVERLAY"]
        datasets_root = os.environ["PCPR050_DATASETS_ROOT"]
        sys.path = [overlay, *list(getattr(sys, "path", []))[1:]]
        for name in list(sys.modules):
            if name == "ipfs_datasets_py" or name.startswith("ipfs_datasets_py."):
                del sys.modules[name]
            if name in {"ipfs_kit_py", "ipfs_accelerate_py"} or name.startswith(
                ("ipfs_kit_py.", "ipfs_accelerate_py.")
            ):
                del sys.modules[name]

        import ipfs_datasets_py

        from ipfs_datasets_py.assurance.schema_packaging import load_schema_catalog

        catalog = load_schema_catalog()
        sibling_hits = {}
        for name in ("ipfs_kit_py", "ipfs_accelerate_py"):
            try:
                imported = __import__(name)
                location = getattr(imported, "__file__", "") or ""
                sibling_hits[name] = location
            except Exception as exc:
                sibling_hits[name] = type(exc).__name__

        def _is_sibling_source(location: str) -> bool:
            if not location or location.endswith("Error"):
                return False
            resolved = os.path.realpath(location)
            root = os.path.realpath(datasets_root)
            return resolved.startswith(root + os.sep) or os.path.dirname(
                resolved
            ) == root

        sibling_source_imported = any(
            _is_sibling_source(str(value)) for value in sibling_hits.values()
        )
        path_has_datasets_root = os.path.realpath(datasets_root) in {
            os.path.realpath(part) for part in sys.path if part
        }
        payload = {
            "import_ok": True,
            "version": getattr(ipfs_datasets_py, "__version__", None),
            "schema_catalog_loaded": isinstance(catalog, dict),
            "requires_sibling_tests_tree": catalog.get(
                "requires_sibling_tests_tree"
            ),
            "sibling_hits": sibling_hits,
            "sibling_source_imported": sibling_source_imported,
            "path_has_datasets_root": path_has_datasets_root,
            "network_effects": [e for e in effects if e.get("kind") == "network"],
            "sys_path_injection": path_has_datasets_root,
        }
        print("PCPR050::" + json.dumps(payload, sort_keys=True, default=str))
        """
    )
    try:
        os.symlink(
            root / "ipfs_datasets_py",
            overlay / "ipfs_datasets_py",
            target_is_directory=True,
        )
        env = {
            "PATH": os.environ.get("PATH", SEALED_PATH),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PCPR050_OVERLAY": str(overlay),
            "PCPR050_DATASETS_ROOT": str(root),
            "HOME": os.environ.get(
                "HOME", "/tmp/ipfs-accelerate-validation-home-pcpr050"
            ),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        }
        completed = subprocess.run(
            [python, "-c", script],
            cwd=str(overlay),
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        shutil.rmtree(overlay, ignore_errors=True)
        return {
            "status": "failed",
            "evidence_kind": "measured_hermetic",
            "import_ok": False,
            "sibling_source_imported": False,
            "reason": f"Isolated import subprocess failed: {exc}",
        }
    shutil.rmtree(overlay, ignore_errors=True)
    if completed.returncode != 0:
        return {
            "status": "failed",
            "evidence_kind": "measured_hermetic",
            "import_ok": False,
            "sibling_source_imported": False,
            "exit_code": completed.returncode,
            "reason": "Isolated import subprocess did not exit 0.",
        }
    line = next(
        (ln for ln in completed.stdout.splitlines() if ln.startswith("PCPR050::")),
        None,
    )
    if line is None:
        return {
            "status": "failed",
            "evidence_kind": "measured_hermetic",
            "import_ok": False,
            "sibling_source_imported": False,
            "reason": "Isolated import subprocess emitted no PCPR050 observation.",
        }
    observation = json.loads(line[len("PCPR050::") :])
    ok = (
        observation.get("import_ok") is True
        and observation.get("schema_catalog_loaded") is True
        and observation.get("sibling_source_imported") is False
        and observation.get("sys_path_injection") is False
        and not observation.get("network_effects")
    )
    return {
        "status": "observed",
        "evidence_kind": "measured_hermetic",
        "import_ok": bool(observation.get("import_ok")),
        "schema_catalog_loaded": bool(observation.get("schema_catalog_loaded")),
        "sibling_source_imported": bool(
            observation.get("sibling_source_imported")
        ),
        "sys_path_injection": bool(observation.get("sys_path_injection")),
        "network_effects": bool(observation.get("network_effects")),
        "version": observation.get("version"),
        "sibling_kit": observation.get("sibling_hits", {}).get("ipfs_kit_py"),
        "sibling_accelerate": observation.get("sibling_hits", {}).get(
            "ipfs_accelerate_py"
        ),
        "ok": ok,
        "reason": (
            "Isolated import succeeded without sibling source trees, sys.path "
            "injection, or network."
            if ok
            else "Isolated import still requires a sibling tree or mutates path/network."
        ),
    }


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def inspect_wheel_members(path: Path) -> dict[str, Any]:
    names: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = sorted(archive.namelist())
    sibling_hits = [
        name
        for name in names
        if name.startswith("ipfs_kit_py/")
        or name.startswith("ipfs_accelerate_py/")
        or "/ipfs_kit_py/" in name
        or "/ipfs_accelerate_py/" in name
    ]
    package_prefix = f"{PACKAGE_NAME}/"
    return {
        "member_count": len(names),
        "has_package": any(
            name.startswith(package_prefix)
            or f".data/purelib/{package_prefix}" in name
            or name.endswith(f".data/purelib/{package_prefix}__init__.py")
            for name in names
        ),
        "has_assurance_schema_catalog": any(
            name.endswith("assurance/schemas/catalog.json") for name in names
        ),
        "sibling_members": sibling_hits,
        "license_present": any(
            name.endswith("LICENSE") or name.endswith("LICENSE.txt")
            for name in names
        ),
        "platform_data_layout": any(".data/purelib/" in name for name in names),
    }


def probe_hermetic_distribution_build(
    root: Path,
    *,
    python_executable: str | None = None,
    dist_dir: Path | None = None,
    build: bool = False,
) -> dict[str, Any]:
    """Optionally build wheel+sdist in a temp dir. Never a published release."""

    python = python_executable or (
        SEALED_PYTHON if Path(SEALED_PYTHON).is_file() else sys.executable
    )
    setuptools_origin = _sealed_python_module_origin("setuptools")
    wheel_origin = _sealed_python_module_origin("wheel")
    build_origin = _sealed_python_module_origin("build")
    tools = {
        "python": python if python else "unavailable",
        "setuptools": setuptools_origin,
        "wheel": wheel_origin,
        "build": build_origin,
    }
    if not build:
        return {
            "status": "unavailable",
            "evidence_kind": "unavailable",
            "reason": (
                "Hermetic distribution build was not requested. Source-tree "
                "dist/ is not a live artifact."
            ),
            "tools": tools,
            "wheel": None,
            "sdist": None,
        }
    missing = [
        name
        for name, origin in (
            ("python", python),
            ("setuptools", setuptools_origin),
            ("wheel", wheel_origin),
            ("build", build_origin),
        )
        if not origin or origin == "unavailable"
    ]
    if missing:
        return {
            "status": "unavailable",
            "evidence_kind": "unavailable",
            "reason": (
                "Sealed-environment build tools are absent: "
                + ", ".join(missing)
            ),
            "tools": tools,
            "wheel": None,
            "sdist": None,
        }
    out_dir = dist_dir or Path(tempfile.mkdtemp(prefix="pcpr050-dist-"))
    out_dir.mkdir(parents=True, exist_ok=True)
    env = {
        "PATH": SEALED_PATH,
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "SOURCE_DATE_EPOCH": "0",
        "HOME": "/tmp/ipfs-accelerate-validation-home-pcpr050",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
    }
    try:
        completed = subprocess.run(
            [
                python,
                "-m",
                "build",
                "--wheel",
                "--sdist",
                "--outdir",
                str(out_dir),
            ],
            cwd=str(root),
            env=env,
            capture_output=True,
            text=True,
            timeout=1800,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "status": "failed",
            "evidence_kind": "measured_hermetic",
            "reason": f"Hermetic build subprocess failed: {exc}",
            "tools": tools,
            "wheel": None,
            "sdist": None,
        }
    wheels = sorted(out_dir.glob("*.whl"))
    sdists = sorted(out_dir.glob("*.tar.gz"))
    if completed.returncode != 0 or not wheels or not sdists:
        return {
            "status": "failed",
            "evidence_kind": "measured_hermetic",
            "reason": "Hermetic build did not produce both wheel and sdist.",
            "exit_code": completed.returncode,
            "tools": tools,
            "wheel": None,
            "sdist": None,
            "stderr_tail": (completed.stderr or "")[-2000:],
        }
    wheel_path = wheels[0]
    sdist_path = sdists[0]
    members = inspect_wheel_members(wheel_path)
    return {
        "status": "observed",
        "evidence_kind": "measured_hermetic",
        "reason": (
            "Hermetic wheel and sdist were built in a private directory. "
            "They are not a published PCPR release."
        ),
        "tools": tools,
        "exit_code": 0,
        "wheel": {
            "name": wheel_path.name,
            "bytes": wheel_path.stat().st_size,
            "sha256": _sha256_file(wheel_path),
            "members": members,
        },
        "sdist": {
            "name": sdist_path.name,
            "bytes": sdist_path.stat().st_size,
            "sha256": _sha256_file(sdist_path),
        },
        "sibling_members_in_wheel": members["sibling_members"],
        "published": False,
    }


def current_head_static_probes(
    start: Path | None = None,
    *,
    python_executable: str | None = None,
) -> tuple[OutcomeProbe, ...]:
    root = discover_datasets_root(start)
    probes: list[OutcomeProbe] = []
    if root is None:
        missing = "datasets source root was not found"
        for probe_id in sorted(REQUIRED_GOOD_PROBE_IDS):
            probes.append(_probe(probe_id, False, reason=missing))
        probes.extend(_terminal_negative_probes(root=None))
        return tuple(probes)

    try:
        setup_text = _read_text(root / "setup.py")
        pyproject_text = _read_text(root / "pyproject.toml")
        manifest_text = _read_text(root / "MANIFEST.in")
        init_text = _read_text(root / "ipfs_datasets_py" / "__init__.py")
        requirements_text = _read_text(root / "requirements.txt")
        install_requires = parse_setup_install_requires(setup_text)
        python_requires = parse_setup_python_requires(setup_text)
        python_classifiers = parse_setup_python_classifiers(setup_text)
        setup_excludes = parse_setup_package_excludes(setup_text)
        pyproject = parse_pyproject_clean_package(pyproject_text)
        prunes = parse_manifest_prunes(manifest_text)
        setup_vcs = scan_requirement_text("\n".join(install_requires))
        req_vcs = scan_requirement_text(requirements_text)
        init_sys_path = package_init_injects_sys_path(init_text)
    except (OSError, CleanPackageError, tomllib.TOMLDecodeError) as exc:
        for probe_id in sorted(REQUIRED_GOOD_PROBE_IDS):
            probes.append(_probe(probe_id, False, reason=str(exc)))
        probes.extend(_terminal_negative_probes(root=root))
        return tuple(probes)

    probes.append(
        _probe(
            "install_requires_empty",
            install_requires == (),
            reason=(
                "setup.py install_requires is empty; the core is dependency-free."
                if install_requires == ()
                else "setup.py install_requires is not empty."
            ),
            details={"install_requires": list(install_requires)},
        )
    )
    probes.append(
        _probe(
            "install_requires_has_no_vcs_url",
            not setup_vcs["vcs"] and not setup_vcs["editable"],
            reason=(
                "Release requires contain no VCS or editable markers."
                if not setup_vcs["vcs"] and not setup_vcs["editable"]
                else "Release requires still contain VCS or editable markers."
            ),
            details=setup_vcs,
        )
    )
    probes.append(
        _probe(
            "mutable_git_release_requires",
            bool(setup_vcs["vcs"]),
            reason=(
                "Mutable Git-branch markers are present in install_requires."
                if setup_vcs["vcs"]
                else "install_requires does not pin a mutable Git branch."
            ),
            details=setup_vcs,
        )
    )
    probes.append(
        _probe(
            "editable_local_release_requires",
            bool(setup_vcs["editable"]),
            reason=(
                "Editable local markers are present in install_requires."
                if setup_vcs["editable"]
                else "install_requires does not use editable local paths."
            ),
            details=setup_vcs,
        )
    )
    probes.append(
        _probe(
            "pyproject_has_no_static_dependencies",
            pyproject.get("dependencies") is None,
            reason=(
                "pyproject.toml leaves runtime dependencies dynamic from setup.py."
                if pyproject.get("dependencies") is None
                else "pyproject.toml declares static project.dependencies."
            ),
            details={"dependencies": pyproject.get("dependencies")},
        )
    )
    probes.append(
        _probe(
            "python_requires_agrees",
            python_requires == CANONICAL_PYTHON_REQUIRES
            and pyproject.get("requires_python") == CANONICAL_PYTHON_REQUIRES,
            reason=(
                "setup.py and pyproject.toml both require Python >=3.12."
                if python_requires == CANONICAL_PYTHON_REQUIRES
                else "Python requires metadata does not agree on >=3.12."
            ),
            details={
                "setup": python_requires,
                "pyproject": pyproject.get("requires_python"),
            },
        )
    )
    probes.append(
        _probe(
            "python_classifier_agrees",
            CANONICAL_PYTHON_CLASSIFIER in python_classifiers
            and "Programming Language :: Python :: 3.10" not in python_classifiers,
            reason=(
                "setup.py advertises Python 3.12 and not the stale 3.10 classifier."
                if CANONICAL_PYTHON_CLASSIFIER in python_classifiers
                else "setup.py Python classifier does not match requires-python."
            ),
            details={"classifiers": list(python_classifiers)},
        )
    )
    pyproject_classifiers = tuple(pyproject.get("classifiers") or ())
    probes.append(
        _probe(
            "pyproject_python_classifier_agrees",
            CANONICAL_PYTHON_CLASSIFIER in pyproject_classifiers
            and CANONICAL_LICENSE_CLASSIFIER in pyproject_classifiers,
            reason=(
                "pyproject.toml classifiers agree on Python 3.12 and AGPL-3.0-only."
                if CANONICAL_PYTHON_CLASSIFIER in pyproject_classifiers
                else "pyproject.toml classifiers do not agree with the clean package."
            ),
            details={"classifiers": list(pyproject_classifiers)},
        )
    )
    sibling_excluded = all(
        marker in setup_excludes and marker in pyproject.get("find_exclude", [])
        for marker in SETUP_PACKAGE_EXCLUDES
    )
    probes.append(
        _probe(
            "sibling_packages_excluded",
            sibling_excluded,
            reason=(
                "setup.py and pyproject.toml exclude sibling kit/accelerate packages."
                if sibling_excluded
                else "Sibling kit/accelerate packages are not excluded from the find."
            ),
            details={
                "setup_excludes": list(setup_excludes),
                "pyproject_excludes": list(pyproject.get("find_exclude") or []),
            },
        )
    )
    prune_ok = all(line in prunes for line in MANIFEST_PRUNE_LINES)
    probes.append(
        _probe(
            "sibling_submodules_pruned",
            prune_ok,
            reason=(
                "MANIFEST.in prunes sibling submodule trees from the sdist."
                if prune_ok
                else "MANIFEST.in does not prune sibling submodule trees."
            ),
            details={"prunes": list(prunes)},
        )
    )
    table = pyproject.get("clean_package") or {}
    table_ok = (
        table.get("schema") == SCHEMA
        and table.get("interface") == INTERFACE
        and table.get("requires-sibling-source-trees") is False
        and table.get("mutable-git-release-requires") is False
        and table.get("sys-path-injection") is False
        and table.get("import-network") is False
    )
    probes.append(
        _probe(
            "pyproject_clean_package_table",
            table_ok,
            reason=(
                "pyproject.toml declares the DatasetsCleanPackage@1 constraints."
                if table_ok
                else "pyproject.toml clean-package table is missing or disagrees."
            ),
            details={"table": table},
        )
    )
    probes.append(
        _probe(
            "package_init_has_no_sys_path_injection",
            not init_sys_path,
            reason=(
                "ipfs_datasets_py/__init__.py does not insert sibling paths."
                if not init_sys_path
                else "Package import still mutates sys.path."
            ),
        )
    )
    probes.append(
        _probe(
            "requirements_txt_git_is_not_release_profile",
            not setup_vcs["vcs"],
            reason=(
                "Development VCS pins in requirements.txt are not install_requires "
                "and are not the release profile."
                if not setup_vcs["vcs"]
                else "VCS pins leaked into setup.py install_requires."
            ),
            details={
                "requirements_txt_vcs": list(req_vcs["vcs"]),
                "install_requires_vcs": list(setup_vcs["vcs"]),
                "requirements_txt_role": (
                    "source-checkout-development-and-integration"
                ),
            },
        )
    )

    manifest_ok = False
    manifest_reason = (
        "LogicPlatformManifest does not advertise DatasetsCleanPackage@1"
    )
    try:
        from ipfs_datasets_py.logic.platform.manifest import (
            DEFAULT_LOGIC_PLATFORM_MANIFEST,
        )

        versions = DEFAULT_LOGIC_PLATFORM_MANIFEST.interface_versions
        roots = DEFAULT_LOGIC_PLATFORM_MANIFEST.schema_roots
        operations = DEFAULT_LOGIC_PLATFORM_MANIFEST.operation_versions
        manifest_ok = (
            versions.get(INTERFACE) == "1"
            and roots.get("datasets_clean_package") == SCHEMA
            and operations.get("clean_package") == "1"
            and DEFAULT_LOGIC_PLATFORM_MANIFEST.requires_sibling_repos() is False
            and DEFAULT_LOGIC_PLATFORM_MANIFEST.requires_repository_layout()
            is False
        )
        if manifest_ok:
            manifest_reason = (
                "LogicPlatformManifest advertises DatasetsCleanPackage@1 and "
                "does not require sibling repositories."
            )
    except Exception as exc:  # pragma: no cover - import/shape failure is a probe
        manifest_reason = str(exc)
    probes.append(
        _probe(
            "manifest_advertises_clean_package",
            manifest_ok,
            reason=manifest_reason,
        )
    )

    isolated = probe_isolated_import_without_siblings(
        root,
        python_executable=python_executable,
    )
    probes.append(
        _probe(
            "isolated_import_without_siblings",
            isolated.get("ok") is True,
            evidence_kind=str(isolated.get("evidence_kind") or "measured_hermetic"),
            reason=str(isolated.get("reason") or "isolated import not observed"),
            details={
                "import_ok": isolated.get("import_ok"),
                "schema_catalog_loaded": isolated.get("schema_catalog_loaded"),
                "sibling_source_imported": isolated.get(
                    "sibling_source_imported"
                ),
                "sys_path_injection": isolated.get("sys_path_injection"),
                "network_effects": isolated.get("network_effects"),
                "version": isolated.get("version"),
                "sibling_kit": isolated.get("sibling_kit"),
                "sibling_accelerate": isolated.get("sibling_accelerate"),
            },
        )
    )
    probes.append(
        _probe(
            "sibling_source_imported",
            bool(isolated.get("sibling_source_imported")),
            evidence_kind=str(isolated.get("evidence_kind") or "measured_hermetic"),
            reason=(
                "Isolated import loaded a sibling source tree."
                if isolated.get("sibling_source_imported")
                else "Isolated import did not load a sibling source tree."
            ),
        )
    )
    probes.append(
        _probe(
            "sys_path_injection_observed",
            bool(isolated.get("sys_path_injection")),
            evidence_kind=str(isolated.get("evidence_kind") or "measured_hermetic"),
            reason=(
                "Isolated import injected the source checkout onto sys.path."
                if isolated.get("sys_path_injection")
                else "Isolated import did not inject the source checkout."
            ),
        )
    )

    probes.extend(_terminal_negative_probes(root=root))
    return tuple(probes)


def _terminal_negative_probes(*, root: Path | None) -> tuple[OutcomeProbe, ...]:
    dist_dir = (root / "dist") if root is not None else None
    wheels = ()
    sdists = ()
    if dist_dir is not None and dist_dir.is_dir():
        wheels = tuple(
            sorted(path.name for path in dist_dir.glob("*.whl") if path.is_file())
        )
        sdists = tuple(
            sorted(
                path.name
                for path in dist_dir.glob("*.tar.gz")
                if path.is_file()
            )
        )
    return (
        _probe(
            "simulated_results_represented_as_live",
            False,
            reason="Simulated results are not represented as live.",
        ),
        _probe(
            "runtime_unavailable_represented_as_live",
            False,
            reason="Clean-package probes are not represented as live.",
        ),
        _probe(
            "built_wheel_represented_as_live",
            False,
            reason="No built wheel is represented as a live published release.",
        ),
        _probe(
            "built_sdist_represented_as_live",
            False,
            reason="No built sdist is represented as a live published release.",
        ),
        _probe(
            "published_release_represented_as_live",
            False,
            reason="This task does not publish a PCPR release.",
        ),
        _probe(
            "built_wheel_metadata",
            None if not wheels else True,
            evidence_kind="unavailable" if not wheels else "measured",
            reason=(
                "No built wheel artifact is present in source-tree dist/; hermetic "
                "temp-dir builds are recorded separately and are not a release."
                if not wheels
                else "Source-tree dist/ contains a wheel name; it is not a published release."
            ),
            details={"artifacts": list(wheels)},
        ),
        _probe(
            "built_sdist_metadata",
            None if not sdists else True,
            evidence_kind="unavailable" if not sdists else "measured",
            reason=(
                "No built sdist artifact is present in source-tree dist/; hermetic "
                "temp-dir builds are recorded separately and are not a release."
                if not sdists
                else "Source-tree dist/ contains an sdist name; it is not a published release."
            ),
            details={"artifacts": list(sdists)},
        ),
        _probe(
            "live_solver_qualification",
            None,
            evidence_kind="unavailable",
            reason=(
                "This task does not qualify live solvers. Missing Z3/cvc5/Lean/Coq "
                "evidence stays typed unavailable and is not recorded as False or passing."
            ),
        ),
    )


def qualify_clean_package(probes: Sequence[OutcomeProbe]) -> CleanPackageVerdict:
    if not probes:
        raise CleanPackageError("at least one probe is required")
    normalized: list[OutcomeProbe] = []
    blockers: list[str] = []
    for probe in probes:
        kind = _kind(probe.evidence_kind, "evidence_kind")
        if probe.live and kind != "measured_live":
            raise CleanPackageError("live claims require measured_live evidence")
        if probe.simulated_represented_as_live:
            raise CleanPackageError(
                "simulated results must not be represented as live"
            )
        normalized.append(probe)
        if probe.probe_id in {
            "live_solver_qualification",
            "built_wheel_metadata",
            "built_sdist_metadata",
        }:
            continue
        if probe.probe_id in FORBIDDEN_PRESENT_PROBE_IDS and probe.present is True:
            blockers.append(probe.probe_id)
        if probe.probe_id in REQUIRED_GOOD_PROBE_IDS and probe.present is not True:
            blockers.append(probe.probe_id)

    promotion_status = "rnd_non_promoted"
    _reject_closed_release_value(promotion_status, "promotion_status")
    wheel_kind = next(
        (
            item.evidence_kind
            for item in normalized
            if item.probe_id == "built_wheel_metadata"
        ),
        "unavailable",
    )
    sdist_kind = next(
        (
            item.evidence_kind
            for item in normalized
            if item.probe_id == "built_sdist_metadata"
        ),
        "unavailable",
    )
    isolated = next(
        (
            item.present is True
            for item in normalized
            if item.probe_id == "isolated_import_without_siblings"
        ),
        False,
    )
    sibling_required = not isolated
    git_requires = next(
        (
            item.present is True
            for item in normalized
            if item.probe_id == "mutable_git_release_requires"
        ),
        False,
    )
    payload = {
        "schema": VERDICT_SCHEMA,
        "interface": INTERFACE,
        "task_id": PCPR_050_TASK_ID,
        "goal_id": PCPR_050_GOAL_ID,
        "promotion_status": promotion_status,
        "supervisor_disposition": "supervisor_non_promoted",
        "closed_release_outcome": None,
        "release_claim": False,
        "completion_authoritative": False,
        "contracts_frozen": False,
        "duckdb_or_quack_state_written": False,
        "sibling_source_required": sibling_required,
        "mutable_git_release_requires": git_requires,
        "isolated_import_without_siblings": isolated,
        "simulated_results_represented_as_live": False,
        "live_solver_qualified": False,
        "live_solver_evidence_kind": "unavailable",
        "built_wheel_evidence_kind": wheel_kind,
        "built_sdist_evidence_kind": sdist_kind,
        "this_task_created_competing_authority": False,
        "probes": [item.to_mapping() for item in normalized],
        "blockers": list(dict.fromkeys(blockers)),
    }
    return CleanPackageVerdict(
        schema=VERDICT_SCHEMA,
        interface=INTERFACE,
        promotion_status=promotion_status,
        supervisor_disposition="supervisor_non_promoted",
        closed_release_outcome=None,
        release_claim=False,
        completion_authoritative=False,
        contracts_frozen=False,
        duckdb_or_quack_state_written=False,
        sibling_source_required=sibling_required,
        mutable_git_release_requires=git_requires,
        isolated_import_without_siblings=isolated,
        simulated_results_represented_as_live=False,
        live_solver_qualified=False,
        live_solver_evidence_kind="unavailable",
        built_wheel_evidence_kind=wheel_kind,
        built_sdist_evidence_kind=sdist_kind,
        this_task_created_competing_authority=False,
        probes=tuple(normalized),
        blockers=tuple(dict.fromkeys(blockers)),
        verdict_cid=content_identity(payload),
    )


def qualify_current_head_clean_package(
    start: Path | None = None,
    *,
    python_executable: str | None = None,
) -> CleanPackageVerdict:
    return qualify_clean_package(
        current_head_static_probes(
            start, python_executable=python_executable
        )
    )


def pcpr_050_receipt_promotion(
    verdict: CleanPackageVerdict,
) -> dict[str, Any]:
    if verdict.closed_release_outcome is not None:
        raise CleanPackageError(
            "clean package must not mint a closed release outcome"
        )
    if verdict.release_claim:
        raise CleanPackageError("clean package must not claim a PCPR release")
    if verdict.completion_authoritative:
        raise CleanPackageError("clean package completion is not authoritative")
    if verdict.duckdb_or_quack_state_written:
        raise CleanPackageError(
            "clean package must not write DuckDB or Quack state"
        )
    if verdict.promotion_status in CLOSED_RELEASE_OUTCOMES:
        raise CleanPackageError(
            "promotion_status must not be a closed release outcome"
        )
    return verdict.to_mapping()


# Pinned identity of the ordinary current-head static verdict. Drift means
# the default payload changed and the outer receipt must be regenerated.
CURRENT_HEAD_NON_PROMOTION_VERDICT_CID: Final = (
    "baguqeerawryb6rdga76wqiufrllhy2cotzmjkmomb5dpga4dyumblfe5t3va"
)


__all__ = [
    "CANONICAL_PYTHON_CLASSIFIER",
    "CANONICAL_PYTHON_REQUIRES",
    "CLOSED_RELEASE_OUTCOMES",
    "CURRENT_HEAD_NON_PROMOTION_VERDICT_CID",
    "CleanPackageAdmissionError",
    "CleanPackageError",
    "CleanPackageVerdict",
    "HERMETIC_CANDIDATE_SUITES",
    "INTERFACE",
    "MANIFEST_PRUNE_LINES",
    "OutcomeProbe",
    "PCPR_050_GOAL_ID",
    "PCPR_050_TASK_ID",
    "SCHEMA",
    "SEALED_PATH",
    "SEALED_PYTHON",
    "SIBLING_TREES",
    "clean_package_manifest",
    "content_identity",
    "current_head_static_probes",
    "discover_datasets_root",
    "inspect_wheel_members",
    "observe_sealed_validation_environment",
    "parse_manifest_prunes",
    "parse_pyproject_clean_package",
    "parse_setup_install_requires",
    "pcpr_050_receipt_promotion",
    "probe_hermetic_distribution_build",
    "probe_isolated_import_without_siblings",
    "qualify_clean_package",
    "qualify_current_head_clean_package",
    "scan_requirement_text",
]
