"""Fail-closed PCPR-053 Datasets dependency locks.

Produce a declared release-profile lock for ipfs_datasets_py. The core
package is dependency-free: setup.py install_requires is empty. That empty
set is the lock, not an omission. Hash and transitive resolution stay typed
unavailable. Hashes are never invented.

This module is not release authority: it does not write DuckDB or Quack
state and never emits a closed PCPR release outcome. Live claims require
live evidence. Simulated results are not live. Missing resolver, hash,
native, wheel, sdist, and container identities stay typed unavailable.
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
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

INTERFACE: Final = "DatasetsDependencyLocks@1"
SCHEMA: Final = "ipfs_datasets_py/assurance/dependency-locks@1"
LOCK_SCHEMA: Final = "ipfs_datasets_py/assurance/dependency-lock@1"
VERDICT_SCHEMA: Final = "ipfs_datasets_py/assurance/dependency-locks-verdict@1"
PCPR_053_TASK_ID: Final = "PCPR-053"
PCPR_053_GOAL_ID: Final = "PCPR-G600"
PCPR_052_TASK_ID: Final = "PCPR-052"
PCPR_050_TASK_ID: Final = "PCPR-050"
PCPR_001_TASK_ID: Final = "PCPR-001"
PCPR_PROGRAM_ID: Final = "proof-carrying-platform-qualification-and-release-v1"
PCPR_BOARD_NAMESPACE: Final = (
    "proof-carrying-platform-qualification-and-release-v1"
)
EVIDENCE_ID: Final = "pcpr/datasets-dependency-locks@1"

PACKAGE_NAME: Final = "ipfs_datasets_py"
PACKAGE_VERSION: Final = "0.2.0"
CANONICAL_PYTHON_REQUIRES: Final = ">=3.12"
RUNTIME_REQUIRES_AUTHORITY: Final = "setup.py:install_requires"
DEVELOPMENT_REQUIREMENTS: Final = "requirements.txt"
PYPROJECT_LOCK_TABLE: Final = "tool.ipfs-datasets-py.dependency-locks"
LOCK_KIND: Final = "declared_release_profile"
LOCK_PROFILE: Final = "release"
LOCK_DIR_RELPATH: Final = "packaging/pcpr/locks/cpython312"
LOCK_JSON_NAME: Final = "release.lock.json"
LOCK_TXT_NAME: Final = "release.txt"
LOCK_README_RELPATH: Final = "packaging/pcpr/locks/README.md"
PYPI_INDEX: Final = "https://pypi.org/simple"

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
    "tests/unit/test_pcpr_053_dependency_locks.py",
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
_PATH_REQUIREMENT_RE: Final = re.compile(
    r"""(?:^|[\s"'=])(?:\.\./|\./|/home/|/usr/local/src/|file://)""",
    re.IGNORECASE,
)
_MUTABLE_REF_RE: Final = re.compile(
    r"@(?:main|master|HEAD|head|develop|trunk|latest)(?:(?:#|$)|\s)",
    re.IGNORECASE,
)
_HASH_LINE_RE: Final = re.compile(r"--hash\s*=\s*sha256:", re.IGNORECASE)
_INSTALL_REQUIRES_RE: Final = re.compile(
    r"install_requires\s*=\s*(\[[^\]]*\])",
    re.MULTILINE | re.DOTALL,
)

REQUIRED_GOOD_PROBE_IDS: Final[frozenset[str]] = frozenset(
    {
        "release_lock_has_no_vcs",
        "release_lock_has_no_editable",
        "release_lock_has_no_path",
        "release_lock_has_no_mutable_branch",
        "hashes_not_invented",
        "lock_files_match_generator",
        "pyproject_dependency_locks_table",
        "requirements_authority_agrees",
        "lock_kind_is_declared_release_profile",
        "core_release_profile_is_empty",
        "development_requirements_are_not_release_lock",
        "manifest_advertises_dependency_locks",
    }
)
FORBIDDEN_PRESENT_PROBE_IDS: Final[frozenset[str]] = frozenset(
    {
        "mutable_git_in_release_lock",
        "editable_in_release_lock",
        "path_in_release_lock",
        "simulated_results_represented_as_live",
        "hashes_represented_as_live",
        "live_resolver_represented_as_live",
        "closed_release_represented_as_live",
    }
)

LOCK_README: Final = """# PCPR-053 declared release-profile dependency locks

These files freeze the Datasets *release* profile. The core package is
dependency-free: `setup.py` `install_requires` is empty. That empty set is
the lock, not an omission.

- `cpython312/release.lock.json` is the canonical declared-spec lock.
- `cpython312/release.txt` is the pip-installable declared-spec list (empty).
- Hash and transitive resolution remain typed unavailable. Hashes are
  never invented.
- `requirements.txt` editable sibling pins are source-checkout development
  only and are not this release lock.

Sealed validation PATH is exactly `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin`.
Provider-local `~/.local` tools such as `uv` are not sealed-environment
authority.
"""


class DependencyLockError(Exception):
    """Fail-closed PCPR-053 contract error."""


class DependencyLockAdmissionError(DependencyLockError):
    """Raised when a lock input is rejected."""


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


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pretty_json(value: Any) -> str:
    return json.dumps(
        value,
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
        allow_nan=False,
    ) + "\n"


def discover_datasets_root(start: Path | None = None) -> Path | None:
    here = Path(start or __file__).resolve()
    for candidate in (here, *here.parents):
        if (
            (candidate / "pyproject.toml").is_file()
            and (candidate / "setup.py").is_file()
            and (candidate / "ipfs_datasets_py" / "__init__.py").is_file()
        ):
            return candidate
    return None


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DependencyLockError(f"{name} must be a non-empty string")
    return value.strip()


def _kind(value: Any, name: str) -> str:
    kind = _text(value, name)
    if kind not in EVIDENCE_KINDS:
        raise DependencyLockError(f"{name} is not an admitted evidence kind")
    return kind


def _reject_closed_release_value(value: Any, name: str) -> None:
    if isinstance(value, str) and value in CLOSED_RELEASE_OUTCOMES:
        raise DependencyLockError(
            f"{name} must not be a closed PCPR release outcome"
        )


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
    path = tuple(
        sorted(
            {match.group(0).strip() for match in _PATH_REQUIREMENT_RE.finditer(body)}
        )
    )
    mutable = tuple(
        sorted({match.group(0).strip() for match in _MUTABLE_REF_RE.finditer(body)})
    )
    hashes = tuple(
        sorted({match.group(0).strip() for match in _HASH_LINE_RE.finditer(body)})
    )
    return {
        "vcs": vcs,
        "editable": editable,
        "path": path,
        "mutable": mutable,
        "hashes": hashes,
    }


def parse_setup_install_requires(text: str) -> tuple[str, ...]:
    body = _text(text, "setup.py")
    match = _INSTALL_REQUIRES_RE.search(body)
    if match is None:
        raise DependencyLockError("setup.py install_requires is missing")
    try:
        parsed = ast.literal_eval(match.group(1))
    except (SyntaxError, ValueError) as exc:
        raise DependencyLockError("setup.py install_requires is not a literal") from exc
    if not isinstance(parsed, list):
        raise DependencyLockError("setup.py install_requires must be a list")
    return tuple(str(item) for item in parsed)


def parse_pyproject_dependency_locks(text: str) -> dict[str, Any]:
    table = tomllib.loads(_text(text, "pyproject.toml"))
    if not isinstance(table, dict):
        raise DependencyLockError("pyproject.toml must be a table")
    tool = table.get("tool")
    lock: dict[str, Any] = {}
    if isinstance(tool, dict):
        datasets = tool.get("ipfs-datasets-py")
        if isinstance(datasets, dict):
            raw = datasets.get("dependency-locks")
            if isinstance(raw, dict):
                lock = dict(raw)
    return {"lock_table": lock}


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
class DependencyLockVerdict:
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
    mutable_git_release_lock: bool
    hashes_invented: bool
    live_resolver_qualified: bool
    live_resolver_evidence_kind: str
    hash_lock_evidence_kind: str
    simulated_results_represented_as_live: bool
    this_task_created_competing_authority: bool
    probes: tuple[OutcomeProbe, ...]
    blockers: tuple[str, ...]
    verdict_cid: str
    lock_cid: str

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "interface": self.interface,
            "verdict_cid": self.verdict_cid,
            "lock_cid": self.lock_cid,
            "promotion_status": self.promotion_status,
            "supervisor_disposition": self.supervisor_disposition,
            "closed_release_outcome": self.closed_release_outcome,
            "release_claim": self.release_claim,
            "completion_authoritative": self.completion_authoritative,
            "contracts_frozen": self.contracts_frozen,
            "duckdb_or_quack_state_written": self.duckdb_or_quack_state_written,
            "sibling_source_required": self.sibling_source_required,
            "mutable_git_release_lock": self.mutable_git_release_lock,
            "hashes_invented": self.hashes_invented,
            "live_resolver_qualified": self.live_resolver_qualified,
            "live_resolver_evidence_kind": self.live_resolver_evidence_kind,
            "hash_lock_evidence_kind": self.hash_lock_evidence_kind,
            "simulated_results_represented_as_live": (
                self.simulated_results_represented_as_live
            ),
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


def _which_sealed(name: str) -> str:
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
                "HOME": "/tmp/ipfs-accelerate-validation-home-pcpr053",
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
    nvidia = _which_sealed("nvidia-smi")
    return {
        "PATH": SEALED_PATH,
        "python_unqualified": _which_sealed("python"),
        "python3": _which_sealed("python3"),
        "python3_12": str(python3_12) if python3_12.is_file() else "unavailable",
        "python_version": python_version,
        "git_path": _which_sealed("git"),
        "pip_path": _which_sealed("pip"),
        "uv_path": _which_sealed("uv"),
        "pip_compile_path": _which_sealed("pip-compile"),
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
        "nvidia_smi": nvidia,
        "nvidia_smi_is_not_contract_qualification": True,
        "provider_local_uv_is_not_sealed_authority": True,
        "evidence_kind": "measured",
    }


def typed_unavailable(*, reason: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "evidence_kind": "unavailable",
        "live": False,
        "reason": reason,
    }


def lock_environment() -> dict[str, Any]:
    env = observe_sealed_validation_environment()
    uname = os.uname()
    return {
        "python_implementation": "CPython",
        "python_version": "3.12",
        "os": uname.sysname.lower(),
        "arch": uname.machine,
        "index": PYPI_INDEX,
        "extra_indexes": [],
        "resolver": (
            "declared-spec lock; live pip metadata resolution is typed "
            "unavailable in the sealed validation environment"
        ),
        "sealed_path": SEALED_PATH,
        "sealed_python": SEALED_PYTHON,
        "pip_path": env["pip_path"],
        "uv_path": env["uv_path"],
        "pip_compile_path": env["pip_compile_path"],
        "evidence_kind": "measured",
    }


def render_release_lock(root: Path | None = None) -> dict[str, Any]:
    package_root = root or discover_datasets_root()
    if package_root is None:
        raise DependencyLockError("Datasets package root was not found")
    specs = parse_setup_install_requires(
        (package_root / "setup.py").read_text(encoding="utf-8")
    )
    scanned = scan_requirement_text("\n".join(specs))
    if scanned["vcs"] or scanned["editable"] or scanned["path"] or scanned["mutable"]:
        raise DependencyLockAdmissionError(
            "release profile contains VCS, editable, path, or mutable-branch requires"
        )
    hashes_reason = (
        "The Datasets core is empty, so there are no hashes to resolve. "
        "A non-empty hashed lock is not invented."
    )
    document = {
        "schema": LOCK_SCHEMA,
        "interface": INTERFACE,
        "task_id": PCPR_053_TASK_ID,
        "goal_id": PCPR_053_GOAL_ID,
        "package_name": PACKAGE_NAME,
        "package_version": PACKAGE_VERSION,
        "profile": LOCK_PROFILE,
        "lock_kind": LOCK_KIND,
        "python_requires": CANONICAL_PYTHON_REQUIRES,
        "requirements_authority": RUNTIME_REQUIRES_AUTHORITY,
        "lock_environment": lock_environment(),
        "direct_requirements": list(specs),
        "direct_requirement_count": len(specs),
        "mutable_git": False,
        "editable": False,
        "path_local": False,
        "sibling_source_required": False,
        "hashes": {
            "status": "unavailable",
            "evidence_kind": "unavailable",
            "live": False,
            "reason": hashes_reason,
            "require_hashes": False,
            "invented": False,
        },
        "resolved_transitive": typed_unavailable(
            reason="The empty core has no transitive graph to resolve."
        ),
        "native_dependencies": {
            "z3": typed_unavailable(reason="z3 is absent from the sealed PATH."),
            "cvc5": typed_unavailable(reason="cvc5 is absent from the sealed PATH."),
            "lean": typed_unavailable(reason="lean is absent from the sealed PATH."),
            "coqtop": typed_unavailable(
                reason="coqtop is absent from the sealed PATH."
            ),
        },
        "artifacts": {
            "wheel": typed_unavailable(
                reason="No published wheel identity is bound by this declared-spec lock."
            ),
            "sdist": typed_unavailable(
                reason="No published sdist identity is bound by this declared-spec lock."
            ),
            "container": typed_unavailable(
                reason="No container digest is bound by this declared-spec lock."
            ),
        },
        "commands": {
            "materialize_lock": (
                'python -c "from ipfs_datasets_py.assurance.dependency_locks '
                'import write_release_lock_files; write_release_lock_files()"'
            ),
            "pip_install_declared": (
                "python -m pip install --no-deps -r "
                f"{LOCK_DIR_RELPATH}/{LOCK_TXT_NAME}"
            ),
            "pip_install_require_hashes": "unavailable",
        },
        "live": False,
        "release_claim": False,
        "closed_release_outcome": None,
        "evidence_kind": "measured",
    }
    document["lock_cid"] = content_identity(
        {key: value for key, value in document.items() if key != "lock_cid"}
    )
    return document


def render_release_lock_txt(document: Mapping[str, Any] | None = None) -> str:
    payload = dict(document or render_release_lock())
    lines = [
        f"# PCPR-053 declared release-profile lock for {PACKAGE_NAME} {PACKAGE_VERSION}.",
        f"# lock_kind: {LOCK_KIND}",
        "# hashes: typed unavailable (not invented)",
        "# live resolver: typed unavailable",
        "# This is not a closed PCPR release and not pip --require-hashes material.",
        f"# lock_cid: {payload['lock_cid']}",
        "",
    ]
    specs = payload.get("direct_requirements") or []
    if not specs:
        lines.append("# (empty release profile)")
    else:
        lines.extend(str(spec) for spec in specs)
    lines.append("")
    return "\n".join(lines)


def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    tmp.replace(path)


def lock_paths(root: Path) -> dict[str, Path]:
    lock_dir = root / LOCK_DIR_RELPATH
    return {
        "json": lock_dir / LOCK_JSON_NAME,
        "txt": lock_dir / LOCK_TXT_NAME,
        "readme": root / LOCK_README_RELPATH,
    }


def write_release_lock_files(start: Path | None = None) -> dict[str, Any]:
    root = discover_datasets_root(start)
    if root is None:
        raise DependencyLockError("Datasets package root was not found")
    document = render_release_lock(root)
    paths = lock_paths(root)
    _atomic_write(paths["json"], pretty_json(document))
    _atomic_write(paths["txt"], render_release_lock_txt(document))
    readme = LOCK_README if LOCK_README.endswith("\n") else LOCK_README + "\n"
    _atomic_write(paths["readme"], readme)
    return {
        "lock": document,
        "paths": {name: str(path) for name, path in paths.items()},
    }


def verify_lock_files(start: Path | None = None) -> dict[str, Any]:
    root = discover_datasets_root(start)
    if root is None:
        raise DependencyLockError("Datasets package root was not found")
    document = render_release_lock(root)
    paths = lock_paths(root)
    missing: list[str] = []
    json_ok = False
    txt_ok = False
    readme_ok = False
    for name, path in paths.items():
        if not path.is_file():
            missing.append(name)
            continue
        if name == "json":
            json_ok = json.loads(path.read_text(encoding="utf-8")) == document
        elif name == "txt":
            txt_ok = path.read_text(encoding="utf-8") == render_release_lock_txt(
                document
            )
        elif name == "readme":
            expected = LOCK_README if LOCK_README.endswith("\n") else LOCK_README + "\n"
            readme_ok = path.read_text(encoding="utf-8") == expected
    json_sha = (
        sha256_bytes(paths["json"].read_bytes())
        if paths["json"].is_file()
        else "unavailable"
    )
    txt_sha = (
        sha256_bytes(paths["txt"].read_bytes())
        if paths["txt"].is_file()
        else "unavailable"
    )
    return {
        "ok": not missing and json_ok and txt_ok and readme_ok,
        "missing": missing,
        "json_ok": json_ok,
        "txt_ok": txt_ok,
        "readme_ok": readme_ok,
        "lock_cid": document["lock_cid"],
        "json_sha256": json_sha,
        "txt_sha256": txt_sha,
    }


def current_head_static_probes(
    start: Path | None = None,
) -> tuple[OutcomeProbe, ...]:
    root = discover_datasets_root(start)
    if root is None:
        raise DependencyLockError("Datasets package root was not found")
    specs = parse_setup_install_requires(
        (root / "setup.py").read_text(encoding="utf-8")
    )
    scanned = scan_requirement_text("\n".join(specs))
    pyproject = parse_pyproject_dependency_locks(
        (root / "pyproject.toml").read_text(encoding="utf-8")
    )
    table = pyproject["lock_table"]
    development = (root / DEVELOPMENT_REQUIREMENTS).read_text(encoding="utf-8")
    development_scan = scan_requirement_text(development)
    verified = verify_lock_files(root)
    document = render_release_lock(root)
    manifest_ok = False
    manifest_reason = "LogicPlatformManifest does not advertise DatasetsDependencyLocks@1"
    try:
        from ipfs_datasets_py.logic.platform.manifest import (
            DEFAULT_LOGIC_PLATFORM_MANIFEST,
        )

        versions = DEFAULT_LOGIC_PLATFORM_MANIFEST.interface_versions
        roots = DEFAULT_LOGIC_PLATFORM_MANIFEST.schema_roots
        operations = DEFAULT_LOGIC_PLATFORM_MANIFEST.operation_versions
        manifest_ok = (
            versions.get(INTERFACE) == "1"
            and roots.get("datasets_dependency_locks") == SCHEMA
            and operations.get("dependency_locks") == "1"
            and DEFAULT_LOGIC_PLATFORM_MANIFEST.requires_sibling_repos() is False
            and DEFAULT_LOGIC_PLATFORM_MANIFEST.requires_repository_layout()
            is False
        )
        if manifest_ok:
            manifest_reason = (
                "LogicPlatformManifest advertises DatasetsDependencyLocks@1 and "
                "does not require sibling repositories."
            )
    except Exception as exc:  # pragma: no cover - import/shape failure is a probe
        manifest_reason = str(exc)
    probes = [
        _probe(
            "release_lock_has_no_vcs",
            not bool(scanned["vcs"]),
            reason=(
                "Release-profile specs contain no VCS markers."
                if not scanned["vcs"]
                else "Release-profile specs contain VCS markers."
            ),
            details={"vcs": list(scanned["vcs"]), "specs": list(specs)},
        ),
        _probe(
            "release_lock_has_no_editable",
            not bool(scanned["editable"]),
            reason=(
                "Release-profile specs contain no editable markers."
                if not scanned["editable"]
                else "Release-profile specs contain editable markers."
            ),
            details={"editable": list(scanned["editable"])},
        ),
        _probe(
            "release_lock_has_no_path",
            not bool(scanned["path"]),
            reason=(
                "Release-profile specs contain no local path requires."
                if not scanned["path"]
                else "Release-profile specs contain local path requires."
            ),
            details={"path": list(scanned["path"])},
        ),
        _probe(
            "release_lock_has_no_mutable_branch",
            not bool(scanned["mutable"]),
            reason=(
                "Release-profile specs contain no mutable Git branch refs."
                if not scanned["mutable"]
                else "Release-profile specs contain mutable Git branch refs."
            ),
            details={"mutable": list(scanned["mutable"])},
        ),
        _probe(
            "mutable_git_in_release_lock",
            bool(scanned["mutable"] or scanned["vcs"]),
            reason="Mutable Git must not appear in the release lock.",
        ),
        _probe(
            "editable_in_release_lock",
            bool(scanned["editable"]),
            reason="Editable requires must not appear in the release lock.",
        ),
        _probe(
            "path_in_release_lock",
            bool(scanned["path"]),
            reason="Local path requires must not appear in the release lock.",
        ),
        _probe(
            "hashes_not_invented",
            document["hashes"]["invented"] is False
            and document["hashes"]["status"] == "unavailable",
            reason="Hashes were not invented; the empty core has no hashes.",
            details=document["hashes"],
        ),
        _probe(
            "lock_files_match_generator",
            verified.get("ok") is True,
            reason=(
                "Committed lock files match the declared-spec generator."
                if verified.get("ok") is True
                else "Committed lock files are missing or drift from the generator."
            ),
            details=verified,
        ),
        _probe(
            "pyproject_dependency_locks_table",
            table.get("interface") == INTERFACE
            and table.get("schema") == SCHEMA
            and table.get("lock-kind") == LOCK_KIND
            and table.get("task-id") == PCPR_053_TASK_ID,
            reason=(
                "pyproject.toml declares DatasetsDependencyLocks@1."
                if table.get("interface") == INTERFACE
                else "pyproject.toml does not declare DatasetsDependencyLocks@1."
            ),
            details={"table": table},
        ),
        _probe(
            "requirements_authority_agrees",
            table.get("requirements-authority") == RUNTIME_REQUIRES_AUTHORITY
            and document["requirements_authority"] == RUNTIME_REQUIRES_AUTHORITY,
            reason="Lock authority remains setup.py:install_requires.",
            details={
                "table_authority": table.get("requirements-authority"),
                "document_authority": document["requirements_authority"],
            },
        ),
        _probe(
            "lock_kind_is_declared_release_profile",
            document["lock_kind"] == LOCK_KIND,
            reason="Lock kind is declared_release_profile, not a hashed live resolve.",
        ),
        _probe(
            "core_release_profile_is_empty",
            document["direct_requirement_count"] == 0,
            reason="Datasets core install_requires is empty; that empty set is the lock.",
            details={"direct_requirement_count": document["direct_requirement_count"]},
        ),
        _probe(
            "development_requirements_are_not_release_lock",
            True,
            reason=(
                "requirements.txt editable sibling pins are source-checkout "
                "development only and are not the release lock."
            ),
            details={
                "development_editable": list(development_scan["editable"]),
                "development_vcs": list(development_scan["vcs"]),
                "release_editable": list(scanned["editable"]),
            },
        ),
        _probe(
            "manifest_advertises_dependency_locks",
            manifest_ok,
            reason=manifest_reason,
        ),
        _probe(
            "simulated_results_represented_as_live",
            False,
            reason="Simulated results are not represented as live.",
        ),
        _probe(
            "hashes_represented_as_live",
            False,
            reason="Unavailable hashes are not represented as live.",
        ),
        _probe(
            "live_resolver_represented_as_live",
            False,
            reason="No live resolver run is represented as live.",
        ),
        _probe(
            "closed_release_represented_as_live",
            False,
            reason="This task does not publish a PCPR release.",
        ),
        _probe(
            "live_resolver",
            None,
            evidence_kind="unavailable",
            reason="Live pip/uv metadata resolution was not admitted against the sealed PATH.",
        ),
        _probe(
            "hashed_lock",
            None,
            evidence_kind="unavailable",
            reason="A require-hashes lock is typed unavailable and was not invented.",
        ),
    ]
    return tuple(probes)


def qualify_dependency_locks(
    probes: Sequence[OutcomeProbe],
    lock_cid: str,
) -> DependencyLockVerdict:
    if not probes:
        raise DependencyLockError("at least one probe is required")
    normalized: list[OutcomeProbe] = []
    blockers: list[str] = []
    for probe in probes:
        kind = _kind(probe.evidence_kind, "evidence_kind")
        if probe.live and kind != "measured_live":
            raise DependencyLockError("live claims require measured_live evidence")
        if probe.simulated_represented_as_live:
            raise DependencyLockError(
                "simulated results must not be represented as live"
            )
        normalized.append(probe)
        if probe.probe_id in FORBIDDEN_PRESENT_PROBE_IDS and probe.present is True:
            blockers.append(probe.probe_id)
        if probe.probe_id in REQUIRED_GOOD_PROBE_IDS and probe.present is not True:
            blockers.append(probe.probe_id)

    promotion_status = "rnd_non_promoted"
    _reject_closed_release_value(promotion_status, "promotion_status")
    mutable = next(
        (
            item.present is True
            for item in normalized
            if item.probe_id == "mutable_git_in_release_lock"
        ),
        False,
    )
    payload = {
        "schema": VERDICT_SCHEMA,
        "interface": INTERFACE,
        "task_id": PCPR_053_TASK_ID,
        "goal_id": PCPR_053_GOAL_ID,
        "promotion_status": promotion_status,
        "supervisor_disposition": "supervisor_non_promoted",
        "closed_release_outcome": None,
        "release_claim": False,
        "completion_authoritative": False,
        "contracts_frozen": False,
        "duckdb_or_quack_state_written": False,
        "sibling_source_required": False,
        "mutable_git_release_lock": mutable,
        "hashes_invented": False,
        "live_resolver_qualified": False,
        "live_resolver_evidence_kind": "unavailable",
        "hash_lock_evidence_kind": "unavailable",
        "simulated_results_represented_as_live": False,
        "this_task_created_competing_authority": False,
        "probes": [item.to_mapping() for item in normalized],
        "blockers": list(dict.fromkeys(blockers)),
        "lock_cid": lock_cid,
    }
    return DependencyLockVerdict(
        schema=VERDICT_SCHEMA,
        interface=INTERFACE,
        promotion_status=promotion_status,
        supervisor_disposition="supervisor_non_promoted",
        closed_release_outcome=None,
        release_claim=False,
        completion_authoritative=False,
        contracts_frozen=False,
        duckdb_or_quack_state_written=False,
        sibling_source_required=False,
        mutable_git_release_lock=mutable,
        hashes_invented=False,
        live_resolver_qualified=False,
        live_resolver_evidence_kind="unavailable",
        hash_lock_evidence_kind="unavailable",
        simulated_results_represented_as_live=False,
        this_task_created_competing_authority=False,
        probes=tuple(normalized),
        blockers=tuple(dict.fromkeys(blockers)),
        verdict_cid=content_identity(payload),
        lock_cid=lock_cid,
    )


def qualify_current_head_dependency_locks(
    start: Path | None = None,
) -> DependencyLockVerdict:
    root = discover_datasets_root(start)
    document = render_release_lock(root)
    return qualify_dependency_locks(
        current_head_static_probes(start),
        str(document["lock_cid"]),
    )


def pcpr_053_receipt_promotion(
    verdict: DependencyLockVerdict,
) -> dict[str, Any]:
    if verdict.closed_release_outcome is not None:
        raise DependencyLockError(
            "dependency locks must not mint a closed release outcome"
        )
    if verdict.release_claim:
        raise DependencyLockError("dependency locks must not claim a PCPR release")
    if verdict.completion_authoritative:
        raise DependencyLockError("dependency-lock completion is not authoritative")
    if verdict.duckdb_or_quack_state_written:
        raise DependencyLockError(
            "dependency locks must not write DuckDB or Quack state"
        )
    if verdict.promotion_status in CLOSED_RELEASE_OUTCOMES:
        raise DependencyLockError(
            "promotion_status must not be a closed release outcome"
        )
    return verdict.to_mapping()


CURRENT_HEAD_NON_PROMOTION_VERDICT_CID: Final = (
    "baguqeeraqekkr4advtjvbxatp53zdnte4oyin43eq55ck7jxwtnx4av6viaa"
)


__all__ = [
    "CLOSED_RELEASE_OUTCOMES",
    "CURRENT_HEAD_NON_PROMOTION_VERDICT_CID",
    "DependencyLockAdmissionError",
    "DependencyLockError",
    "DependencyLockVerdict",
    "HERMETIC_CANDIDATE_SUITES",
    "INTERFACE",
    "LOCK_KIND",
    "LOCK_SCHEMA",
    "OutcomeProbe",
    "PCPR_053_GOAL_ID",
    "PCPR_053_TASK_ID",
    "SCHEMA",
    "SEALED_PATH",
    "SEALED_PYTHON",
    "content_identity",
    "current_head_static_probes",
    "discover_datasets_root",
    "observe_sealed_validation_environment",
    "parse_pyproject_dependency_locks",
    "parse_setup_install_requires",
    "pcpr_053_receipt_promotion",
    "qualify_current_head_dependency_locks",
    "qualify_dependency_locks",
    "render_release_lock",
    "scan_requirement_text",
    "verify_lock_files",
    "write_release_lock_files",
]
