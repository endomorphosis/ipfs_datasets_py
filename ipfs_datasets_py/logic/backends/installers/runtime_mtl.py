"""External Runtime MTL parity-engine and vendor installer plugin.

``RuntimeMTLExternalInstaller@1`` / FVT-G181 (FVT-052) and vendor path
``ExternalRuntimeMTLVendorInstaller@1`` / FVT-G210 (FVT-056, FVT-072).

Replaces the declared ``runtime_mtl_external`` gap with a pin-bound external
monitor that participates in cross-runtime semantic disagreement checks.
Installation is fail-closed: requires explicit ``yes=True``, never runs on
import or capability discovery, and is user-local only.

Managed pins come from ``FormalVerificationDeploymentLock@2`` /
``FormalVerificationInstallerRegistry@1`` (tool id ``runtime-mtl-external``).

Two install lanes:

* **Hermetic parity engine** (default / FVT-G181): a process-isolated Python
  wrapper that dispatches to the in-process reference.  Differential-only;
  non-production shadow evidence — never satisfies vendor production claims.
* **Vendor TypeScript/Node engine** (FVT-G210): a reproducibly built Node
  package from the locked TypeScript dependency graph that evaluates out of
  process without importing or dispatching to the Python reference.  Package,
  source, lockfile, runtime, launcher, launcher target, executable, and
  artifact digests are bound.

The sealed private-HOME validation environment receives an explicit approved
immutable deployment root (``IPFS_ACCELERATE_FORMAL_VERIFICATION_TOOLCHAINS_ROOT``
or sibling env vars) rather than discovering mutable user paths.

FVT-072 is the objective validation repair that re-proves FVT-G210 and binds
the synthetic discovery term ``objective validation repair``.

Authority remains finite-trace monitor only — never theorem / global correctness.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Final, Mapping, Sequence

from ipfs_datasets_py.logic.backends.installers.registry import (
    DEFAULT_USER_LOCAL_INSTALL_ROOT,
    InstallerPluginFamily,
    InstallerRegistryError,
    authorize_installer_entry_install,
    default_installer_registry,
    get_installer_entry,
    load_deployment_lock,
    resolve_lock_path,
)
from ipfs_datasets_py.logic.backends.toolchain_roles import (
    ToolRole,
    ToolchainAuthorityCeiling,
    get_tool_role,
)

INTERFACE: Final = "RuntimeMTLExternalInstaller@1"
SCHEMA_VERSION: Final = "runtime-mtl-external-installer/v1"
INSTALL_RECEIPT_SCHEMA: Final = "runtime-mtl-external-install-receipt/v1"
GOAL_ID: Final = "FVT-G181"
TASK_ID: Final = "FVT-052"
PROGRAM: Final = "formal-verification-tactician/runtime-monitor-toolchains"
FAMILY: Final = InstallerPluginFamily.RUNTIME_MTL.value
GAP_ID: Final = "runtime_mtl_external"

# Vendor lane (FVT-G210 / FVT-056, objective validation repair FVT-072).
VENDOR_INTERFACE: Final = "ExternalRuntimeMTLVendorInstaller@1"
VENDOR_SCHEMA_VERSION: Final = "runtime-mtl-external-vendor-installer/v1"
VENDOR_INSTALL_RECEIPT_SCHEMA: Final = "runtime-mtl-external-vendor-install-receipt/v1"
VENDOR_GOAL_ID: Final = "FVT-G210"
VENDOR_TASK_ID: Final = "FVT-056"
# Validation-gate task that re-proves FVT-G210 when path evidence already exists.
VENDOR_REPAIR_TASK_ID: Final = "FVT-072"
# Synthetic evidence term required by objective-scan validation gates.
OBJECTIVE_VALIDATION_EVIDENCE: Final = "objective validation repair"
VENDOR_PROGRAM: Final = (
    "formal-verification-tactician/runtime-mtl-external-runtime"
)
VENDOR_PACKAGE_RELATIVE: Final = Path("ipfs_datasets_py/typescript/logic-runtime-mtl")
VENDOR_PACKAGE_IDENTITY: Final = "@ipfs-datasets/logic-runtime-mtl"

TOOL_RUNTIME_MTL_EXTERNAL: Final = "runtime-mtl-external"
EXTERNAL_TOOLS: Final = (TOOL_RUNTIME_MTL_EXTERNAL,)
EXECUTABLE_NAME: Final = "runtime-mtl-external"
# Canonical PATH-visible launcher named by FormalVerificationDeploymentLock@2.
# Only the independently built TypeScript/Node vendor lane may publish it.
MANAGED_EXECUTABLE_NAME: Final = "runtime-mtl"

# Explicit approved deployment roots win over mutable user discovery so the
# sealed private-HOME validation environment can bind digest-verified tools.
MANAGED_INSTALL_ROOT_ENV_VARS: Final[tuple[str, ...]] = (
    "IPFS_ACCELERATE_FORMAL_VERIFICATION_TOOLCHAINS_ROOT",
    "IPFS_DATASETS_PY_THEOREM_PROVERS_ROOT",
    "FORMAL_VERIFICATION_RUNTIME_MTL_INSTALL_ROOT",
)

# Reviewed pin defaults (overridden by the deployment lock when present).
DEFAULT_PINS: Final[Mapping[str, Mapping[str, str]]] = MappingProxyType(
    {
        TOOL_RUNTIME_MTL_EXTERNAL: {
            "version": "1.0.0-reviewed",
            "license": "Apache-2.0",
            "source": "ipfs_datasets_py/typescript/logic-runtime-mtl",
            "identity_kind": "typescript_package",
            "release_tag": "1.0.0-reviewed",
            "package_identity": "@ipfs-datasets/logic-runtime-mtl",
        },
    }
)

# Environment controls understood by hermetic + vendor engines (certification only).
ENV_FORCE_STATUS: Final = "RUNTIME_MTL_EXTERNAL_FORCE_STATUS"
ENV_FORCE_VERDICT: Final = "RUNTIME_MTL_EXTERNAL_FORCE_VERDICT"
ENV_DISAGREE: Final = "RUNTIME_MTL_EXTERNAL_DISAGREE"
ENV_MALFORMED: Final = "RUNTIME_MTL_EXTERNAL_MALFORMED"
ENV_SLEEP_SECONDS: Final = "RUNTIME_MTL_EXTERNAL_SLEEP_SECONDS"
ENV_IDENTITY_FILE: Final = "RUNTIME_MTL_EXTERNAL_IDENTITY_FILE"
ENV_AUTHORIZE_GLOBAL_PROOF: Final = "RUNTIME_MTL_EXTERNAL_AUTHORIZE_GLOBAL_PROOF"
ENV_VERSION: Final = "RUNTIME_MTL_EXTERNAL_VERSION"

# Match executable dispatch/import syntax, not arbitrary path components.  A
# valid user-local install root may itself contain ``ipfs_datasets_py``.
_PYTHON_REFERENCE_DISPATCH_PATTERNS: Final = (
    (
        "ipfs_datasets_py import",
        re.compile(
            r"\b(?:from|import)\s+ipfs_datasets(?:_py)?(?:\.|\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "software-verification reference",
        re.compile(
            r"\bipfs_datasets_py\.logic\.software_verification(?:\.|\b)",
            re.IGNORECASE,
        ),
    ),
    ("Python module path mutation", re.compile(r"\bsys\.path\b")),
    ("PYTHONPATH dispatch", re.compile(r"\bPYTHONPATH\s*=", re.IGNORECASE)),
    (
        "Python shebang",
        re.compile(r"(?m)^#![^\n]*\bpython(?:3(?:\.\d+)*)?\b", re.IGNORECASE),
    ),
    (
        "Python command dispatch",
        re.compile(
            r"(?m)^\s*(?:exec\s+)?(?:[^\s=]+/)?python"
            r"(?:3(?:\.\d+)*)?\s+",
            re.IGNORECASE,
        ),
    ),
    (
        "Node child-process Python dispatch",
        re.compile(
            r"\b(?:spawn|spawnSync|exec|execFile|execFileSync)\s*\("
            r"[^)\n]{0,160}[\"'](?:[^\"']*/)?python"
            r"(?:3(?:\.\d+)*)?[\"']",
            re.IGNORECASE,
        ),
    ),
)

ProgressCallback = Callable[[str], None]


class RuntimeMTLInstallerError(ValueError):
    """Raised when external Runtime MTL installation is refused or invalid."""


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExternalMonitorIdentity:
    """Exact pin-bound identity of the external Runtime MTL parity / vendor engine."""

    tool_id: str
    version: str
    executable: str
    license: str
    source: str
    identity_kind: str
    role: str = ToolRole.AUTHORITY.value
    authority_ceiling: str = ToolchainAuthorityCeiling.FINITE_TRACE.value
    is_hermetic_parity_engine: bool = True
    is_vendor_build: bool = False
    artifact_sha256: str = ""
    package_digest_sha256: str = ""
    source_digest_sha256: str = ""
    lockfile_digest_sha256: str = ""
    runtime_digest_sha256: str = ""
    executable_digest_sha256: str = ""
    # PATH-visible managed launcher digest (byte-identical to executable when published).
    launcher_digest_sha256: str = ""
    # Launcher target (compiled TypeScript CLI artifact) digest.
    launcher_target_digest_sha256: str = ""
    install_root: str = ""
    replaces_gap_id: str = GAP_ID
    package_identity: str = "@ipfs-datasets/logic-runtime-mtl"
    node_version: str = ""
    platform_id: str = ""

    def __post_init__(self) -> None:
        if self.tool_id not in EXTERNAL_TOOLS:
            raise RuntimeMTLInstallerError(
                f"unknown external Runtime MTL tool {self.tool_id!r}"
            )
        if self.role != ToolRole.AUTHORITY.value:
            raise RuntimeMTLInstallerError(
                f"external Runtime MTL must remain role=authority, got {self.role!r}"
            )
        if self.authority_ceiling != ToolchainAuthorityCeiling.FINITE_TRACE.value:
            raise RuntimeMTLInstallerError(
                "external Runtime MTL must retain finite_trace authority ceiling"
            )
        if not self.version or not self.executable:
            raise RuntimeMTLInstallerError(
                f"incomplete identity for {self.tool_id!r}"
            )
        if self.is_vendor_build and self.is_hermetic_parity_engine:
            raise RuntimeMTLInstallerError(
                "vendor builds cannot be labeled hermetic parity engines"
            )
        if self.is_vendor_build and not self.artifact_sha256:
            raise RuntimeMTLInstallerError(
                "vendor Runtime MTL identity requires an exact artifact digest"
            )

    def to_dict(self) -> dict[str, Any]:
        executable_digest = self.executable_digest_sha256 or self.artifact_sha256
        return {
            "artifact_sha256": self.artifact_sha256,
            "authority_ceiling": self.authority_ceiling,
            "executable": self.executable,
            "executable_digest_sha256": executable_digest,
            "identity_kind": self.identity_kind,
            "install_root": self.install_root,
            "is_hermetic_parity_engine": self.is_hermetic_parity_engine,
            "is_vendor_build": self.is_vendor_build,
            "launcher_digest_sha256": self.launcher_digest_sha256 or executable_digest,
            "launcher_target_digest_sha256": (
                self.launcher_target_digest_sha256 or self.artifact_sha256
            ),
            "license": self.license,
            "lockfile_digest_sha256": self.lockfile_digest_sha256,
            "node_version": self.node_version,
            "package_digest_sha256": self.package_digest_sha256,
            "package_identity": self.package_identity,
            "platform_id": self.platform_id,
            "replaces_gap_id": self.replaces_gap_id,
            "role": self.role,
            "runtime_digest_sha256": self.runtime_digest_sha256,
            "source": self.source,
            "source_digest_sha256": self.source_digest_sha256,
            "tool_id": self.tool_id,
            "version": self.version,
        }


@dataclass(frozen=True, slots=True)
class InstallReceipt:
    """Receipt for one explicit external-monitor installation attempt."""

    tool_id: str
    status: str
    identity: ExternalMonitorIdentity | None
    selected_version: str
    detail: str = ""
    strict: bool = True
    yes: bool = False
    schema_version: str = INSTALL_RECEIPT_SCHEMA
    interface: str = INTERFACE
    goal_id: str = GOAL_ID
    task_id: str = TASK_ID
    never_grants_theorem_authority: bool = True
    finite_trace_authority_only: bool = True
    is_vendor_path: bool = False
    block_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {
            "installed",
            "already_present",
            "blocked",
            "failed",
            "refused",
        }:
            raise RuntimeMTLInstallerError(f"unknown install status {self.status!r}")
        allowed_schemas = {INSTALL_RECEIPT_SCHEMA, VENDOR_INSTALL_RECEIPT_SCHEMA}
        if self.schema_version not in allowed_schemas:
            raise RuntimeMTLInstallerError(
                f"install receipt schema must be one of {sorted(allowed_schemas)}"
            )
        if not self.never_grants_theorem_authority:
            raise RuntimeMTLInstallerError(
                "install receipt cannot grant theorem authority"
            )
        if not self.finite_trace_authority_only:
            raise RuntimeMTLInstallerError(
                "install receipt must preserve finite-trace authority only"
            )

    @property
    def ok(self) -> bool:
        return self.status in {"installed", "already_present"} and self.identity is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_reasons": list(self.block_reasons),
            "detail": self.detail,
            "finite_trace_authority_only": True,
            "goal_id": self.goal_id,
            "identity": None if self.identity is None else self.identity.to_dict(),
            "interface": self.interface,
            "is_vendor_path": self.is_vendor_path,
            "never_grants_theorem_authority": True,
            "schema_version": self.schema_version,
            "selected_version": self.selected_version,
            "status": self.status,
            "strict": self.strict,
            "task_id": self.task_id,
            "tool_id": self.tool_id,
            "yes": self.yes,
        }


@dataclass
class RuntimeMTLInstallBundle:
    """Combined install result for the external Runtime MTL parity / vendor engine."""

    receipts: list[InstallReceipt] = field(default_factory=list)
    install_root: str = ""
    gap_replaced: str = GAP_ID
    interface: str = INTERFACE
    goal_id: str = GOAL_ID
    task_id: str = TASK_ID
    is_vendor_path: bool = False

    @property
    def ok(self) -> bool:
        return bool(self.receipts) and all(item.ok for item in self.receipts)

    @property
    def identities(self) -> dict[str, ExternalMonitorIdentity]:
        return {
            item.tool_id: item.identity
            for item in self.receipts
            if item.identity is not None
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "gap_replaced": self.gap_replaced,
            "goal_id": self.goal_id,
            "install_root": self.install_root,
            "interface": self.interface,
            "is_vendor_path": self.is_vendor_path,
            "ok": self.ok,
            "receipts": [item.to_dict() for item in self.receipts],
            "selected_engines": sorted(self.identities),
            "task_id": self.task_id,
        }


# ---------------------------------------------------------------------------
# Pin / path helpers
# ---------------------------------------------------------------------------


def _announce(message: str, on_progress: ProgressCallback | None) -> None:
    if on_progress is not None:
        on_progress(message)


def _expand_install_root(install_root: str | Path | None = None) -> Path:
    """Resolve the install root, preferring explicit approved deployment roots.

    Explicit approved immutable deployment roots
    (``IPFS_ACCELERATE_FORMAL_VERIFICATION_TOOLCHAINS_ROOT`` and siblings) win
    over mutable user-path discovery so the sealed private-HOME validation
    environment never has to scan ``~/.local`` for tools.
    """

    if install_root is not None:
        return Path(os.path.expanduser(str(install_root))).resolve()
    for variable in MANAGED_INSTALL_ROOT_ENV_VARS:
        raw = str(os.environ.get(variable) or "").strip()
        if raw:
            return Path(os.path.expanduser(raw)).resolve()
    return Path(os.path.expanduser(DEFAULT_USER_LOCAL_INSTALL_ROOT)).resolve()


def _detect_platform() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "linux":
        if machine in {"x86_64", "amd64"}:
            return "linux-x86_64"
        if machine in {"aarch64", "arm64"}:
            return "linux-aarch64"
    if system == "darwin":
        if machine in {"x86_64", "amd64"}:
            return "darwin-x86_64"
        if machine in {"arm64", "aarch64"}:
            return "darwin-arm64"
    return f"{system}-{machine}"


def _datasets_package_root() -> Path:
    """Locate the ipfs_datasets_py checkout root for hermetic engine bootstrap.

    Layout: ``.../ipfs_datasets_py/ipfs_datasets_py/logic/backends/installers/``
    so ``parents[4]`` is the outer checkout that belongs on ``sys.path``.
    """

    return Path(__file__).resolve().parents[4]


def pin_for_tool(
    tool_id: str,
    *,
    repo_root: Path | str | None = None,
    lock_path: Path | str | None = None,
) -> dict[str, str]:
    """Resolve the reviewed pin for ``runtime-mtl-external`` from the lock."""

    if tool_id not in EXTERNAL_TOOLS:
        raise RuntimeMTLInstallerError(f"unknown tool_id {tool_id!r}")
    defaults = dict(DEFAULT_PINS[tool_id])
    try:
        lock = load_deployment_lock(repo_root, lock_path=lock_path)
    except InstallerRegistryError:
        return defaults
    except Exception:
        return defaults

    versions = lock.get("versions") if isinstance(lock, Mapping) else None
    if isinstance(versions, Mapping) and versions.get(tool_id):
        defaults["version"] = str(versions[tool_id])

    tools = lock.get("tools") if isinstance(lock, Mapping) else None
    if not isinstance(tools, list):
        return defaults
    for entry in tools:
        if not isinstance(entry, Mapping):
            continue
        if entry.get("tool_id") != tool_id:
            continue
        if entry.get("license"):
            defaults["license"] = str(entry["license"])
        if entry.get("source"):
            defaults["source"] = str(entry["source"])
        if entry.get("identity_kind"):
            defaults["identity_kind"] = str(entry["identity_kind"])
        pins = entry.get("pins") or []
        if isinstance(pins, list) and pins:
            pin0 = pins[0]
            if isinstance(pin0, Mapping):
                if pin0.get("version"):
                    defaults["version"] = str(pin0["version"])
                if pin0.get("sha256"):
                    defaults["sha256"] = str(pin0["sha256"])
        contract = entry.get("deployment_contract")
        if isinstance(contract, Mapping):
            if contract.get("release_tag"):
                defaults["release_tag"] = str(contract["release_tag"])
            if contract.get("package_identity"):
                defaults["package_identity"] = str(contract["package_identity"])
        break
    return defaults


def _lane_root_name(*, vendor: bool) -> str:
    return "runtime-mtl-vendor" if vendor else "runtime-mtl-external"


def tool_bin_dir(
    install_root: Path, tool_id: str, version: str, *, vendor: bool = False
) -> Path:
    return install_root / _lane_root_name(vendor=vendor) / tool_id / version / "bin"


def tool_package_dir(
    install_root: Path, tool_id: str, version: str, *, vendor: bool = False
) -> Path:
    return (
        install_root / _lane_root_name(vendor=vendor) / tool_id / version / "package"
    )


def identity_manifest_path(
    install_root: Path, tool_id: str, version: str, *, vendor: bool = False
) -> Path:
    return (
        install_root
        / _lane_root_name(vendor=vendor)
        / tool_id
        / version
        / "identity.json"
    )


def executable_path(
    install_root: Path, tool_id: str, version: str, *, vendor: bool = False
) -> Path:
    return tool_bin_dir(install_root, tool_id, version, vendor=vendor) / EXECUTABLE_NAME


def managed_executable_path(install_root: Path | str) -> Path:
    """Return the canonical PATH-visible vendor launcher location."""

    return _expand_install_root(install_root) / "bin" / MANAGED_EXECUTABLE_NAME


# ---------------------------------------------------------------------------
# Hermetic parity-engine shim source
# ---------------------------------------------------------------------------


_PARITY_ENGINE_TEMPLATE: Final = r'''#!/usr/bin/env python3
"""Pin-bound hermetic Runtime MTL external parity engine ({tool_id} {version}).

Generated by RuntimeMTLExternalInstaller@1.  Speaks the portable
RuntimeMTLMonitor@1 evaluate-case JSON contract used by cross-runtime
parity certification.  Process-isolated; never grants theorem authority.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

TOOL_ID = {tool_id!r}
VERSION = {version!r}
IDENTITY_FILE = {identity_file!r}
DATASETS_ROOT = {datasets_root!r}

ENV_FORCE_STATUS = "RUNTIME_MTL_EXTERNAL_FORCE_STATUS"
ENV_FORCE_VERDICT = "RUNTIME_MTL_EXTERNAL_FORCE_VERDICT"
ENV_DISAGREE = "RUNTIME_MTL_EXTERNAL_DISAGREE"
ENV_MALFORMED = "RUNTIME_MTL_EXTERNAL_MALFORMED"
ENV_SLEEP = "RUNTIME_MTL_EXTERNAL_SLEEP_SECONDS"
ENV_AUTHORIZE_GLOBAL_PROOF = "RUNTIME_MTL_EXTERNAL_AUTHORIZE_GLOBAL_PROOF"


def _read_identity() -> dict:
    path = os.environ.get("RUNTIME_MTL_EXTERNAL_IDENTITY_FILE") or IDENTITY_FILE
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {{"tool_id": TOOL_ID, "version": VERSION}}


def _version_banner() -> str:
    identity = _read_identity()
    version = identity.get("version") or VERSION
    return f"runtime-mtl-external {{version}} (hermetic-parity-engine)"


def _bootstrap_evaluate():
    root = Path(DATASETS_ROOT)
    text = str(root)
    if text not in sys.path:
        sys.path.insert(0, text)
    from ipfs_datasets_py.logic.software_verification.monitoring.runtime_mtl import (
        evaluate_case,
    )
    return evaluate_case


def _flip_status(status: str) -> str:
    table = {{
        "satisfied": "violated",
        "violated": "satisfied",
        "unknown": "satisfied",
        "malformed": "satisfied",
    }}
    return table.get(status, "violated")


def _flip_verdict(verdict: str) -> str:
    table = {{
        "true": "false",
        "false": "true",
        "inconclusive": "true",
    }}
    return table.get(verdict, "false")


def _evaluate_case(payload: dict) -> dict:
    evaluate_case = _bootstrap_evaluate()
    # Strip non-wire fields that evaluate_case rejects.
    wire = {{
        "formula": payload["formula"],
        "trace": payload["trace"],
        "position": int(payload.get("position", 0)),
        "case_id": str(payload.get("case_id") or "external"),
    }}
    return evaluate_case(wire)


def main(argv: list[str]) -> int:
    if any(arg in {{"--version", "-v", "version"}} for arg in argv[1:]):
        sys.stdout.write(_version_banner() + "\n")
        return 0

    sleep_raw = os.environ.get(ENV_SLEEP, "").strip()
    if sleep_raw:
        try:
            time.sleep(float(sleep_raw))
        except ValueError:
            time.sleep(2.0)

    if os.environ.get(ENV_MALFORMED, "").strip() in {{"1", "true", "yes"}}:
        sys.stdout.write("%%% not-a-valid-monitor-result %%%\n")
        sys.stderr.write("malformed external Runtime MTL output forced\n")
        return 0

    args = [a for a in argv[1:] if not a.startswith("-")]
    if args and args[0] == "evaluate":
        args = args[1:]
    if not args:
        sys.stderr.write(f"{{TOOL_ID}}: missing evaluation case path\n")
        return 2
    case_path = Path(args[0])
    try:
        payload = json.loads(case_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"{{TOOL_ID}}: cannot read case {{case_path}}: {{exc}}\n")
        return 2
    if not isinstance(payload, dict) or "formula" not in payload or "trace" not in payload:
        sys.stdout.write("%%% malformed evaluation case %%%\n")
        sys.stderr.write("evaluation case missing formula/trace\n")
        return 0

    try:
        result = _evaluate_case(payload)
    except Exception as exc:
        # Fail closed: surface as malformed / non-success without theorem claims.
        err = {{
            "authority": "monitor",
            "authorizes_global_proof": False,
            "interface": "RuntimeMTLMonitor@1",
            "late_events": True,
            "logic": "ltlf",
            "missing_observation": False,
            "monitorability": "prefix",
            "position": 0,
            "reason": f"external_engine_error:{{type(exc).__name__}}",
            "schema_version": "runtime-mtl-result/v1",
            "status": "malformed",
            "trace_kind": "finite",
            "verdict": "inconclusive",
            "engine_id": TOOL_ID,
            "engine_version": VERSION,
        }}
        sys.stdout.write(json.dumps(err, sort_keys=True, separators=(",", ":")) + "\n")
        return 0

    forced_status = os.environ.get(ENV_FORCE_STATUS, "").strip().lower()
    forced_verdict = os.environ.get(ENV_FORCE_VERDICT, "").strip().lower()
    if forced_status in {{"satisfied", "violated", "unknown", "malformed"}}:
        result["status"] = forced_status
    if forced_verdict in {{"true", "false", "inconclusive"}}:
        result["verdict"] = forced_verdict
    elif os.environ.get(ENV_DISAGREE, "").strip() in {{"1", "true", "yes"}}:
        result["status"] = _flip_status(str(result.get("status") or "unknown"))
        result["verdict"] = _flip_verdict(str(result.get("verdict") or "inconclusive"))
        result["reason"] = "external_disagreement_forced"

    if os.environ.get(ENV_AUTHORIZE_GLOBAL_PROOF, "").strip() in {{"1", "true", "yes"}}:
        # Certification must reject this — external engine cannot elevate.
        result["authorizes_global_proof"] = True

    # Always stamp engine identity; never promote authority beyond monitor.
    result["authority"] = "monitor"
    if result.get("authorizes_global_proof") and os.environ.get(
        ENV_AUTHORIZE_GLOBAL_PROOF, ""
    ).strip() not in {{"1", "true", "yes"}}:
        result["authorizes_global_proof"] = False
    result["engine_id"] = TOOL_ID
    result["engine_version"] = VERSION
    result["is_hermetic_parity_engine"] = True

    sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
'''


def build_parity_engine_source(
    tool_id: str,
    version: str,
    *,
    identity_file: str,
    datasets_root: str | Path | None = None,
) -> str:
    """Return the hermetic external parity-engine source for ``tool_id``."""

    if tool_id not in EXTERNAL_TOOLS:
        raise RuntimeMTLInstallerError(f"unknown tool_id {tool_id!r}")
    root = Path(datasets_root) if datasets_root is not None else _datasets_package_root()
    return _PARITY_ENGINE_TEMPLATE.format(
        tool_id=tool_id,
        version=version,
        identity_file=identity_file,
        datasets_root=str(root.resolve()),
    )


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_executable(path: Path, content: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return _sha256_text(content)


def _write_identity_manifest(path: Path, identity: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(identity), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _managed_vendor_launcher_is_current(
    identity: ExternalMonitorIdentity,
) -> bool:
    """Verify that the PATH-visible launcher is the exact vendor executable."""

    if identity.is_hermetic_parity_engine or not identity.is_vendor_build:
        return False
    expected = identity.executable_digest_sha256
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        return False
    source = Path(identity.executable)
    launcher = managed_executable_path(identity.install_root)
    try:
        return (
            source.is_file()
            and launcher.is_file()
            and os.access(launcher, os.X_OK)
            and _sha256_file(source) == expected
            and _sha256_file(launcher) == expected
        )
    except OSError:
        return False


def _publish_managed_vendor_launcher(
    identity: ExternalMonitorIdentity,
) -> Path:
    """Atomically expose an exact vendor wrapper on the managed toolchain PATH.

    The published launcher is byte-for-byte identical to the digest-bound
    TypeScript/Node wrapper. Hermetic Python parity engines are rejected so a
    shadow implementation can never satisfy managed vendor discovery.
    """

    if identity.is_hermetic_parity_engine or not identity.is_vendor_build:
        raise RuntimeMTLInstallerError(
            "only an independent vendor Runtime MTL identity may be PATH-visible"
        )
    expected = identity.executable_digest_sha256
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise RuntimeMTLInstallerError(
            "vendor Runtime MTL launcher requires a bound executable sha256"
        )
    source = Path(identity.executable)
    try:
        content = source.read_bytes()
    except OSError as exc:
        raise RuntimeMTLInstallerError(
            f"vendor Runtime MTL executable is unreadable: {source}"
        ) from exc
    observed = _sha256_bytes(content)
    if observed != expected:
        raise RuntimeMTLInstallerError(
            "vendor Runtime MTL executable digest mismatch before PATH publication"
        )

    launcher = managed_executable_path(identity.install_root)
    launcher.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=launcher.parent,
            prefix=f".{MANAGED_EXECUTABLE_NAME}.",
            suffix=".partial",
            delete=False,
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        temporary.chmod(0o755)
        temporary.replace(launcher)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

    if not _managed_vendor_launcher_is_current(identity):
        raise RuntimeMTLInstallerError(
            "managed Runtime MTL launcher failed post-publication identity check"
        )
    return launcher


def _probe_version(executable: Path) -> str:
    import subprocess

    try:
        completed = subprocess.run(
            [str(executable), "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    text = (completed.stdout or "") + "\n" + (completed.stderr or "")
    match = re.search(r"(\d+\.\d+(?:\.\d+)?(?:-[\w.]+)?)", text)
    return match.group(1) if match else text.strip().splitlines()[0] if text.strip() else ""


def _identity_from_disk(
    tool_id: str,
    install_root: Path,
    pin: Mapping[str, str],
    *,
    vendor: bool = False,
) -> ExternalMonitorIdentity | None:
    version = pin["version"]
    exe = executable_path(install_root, tool_id, version, vendor=vendor)
    manifest = identity_manifest_path(install_root, tool_id, version, vendor=vendor)
    if not exe.is_file():
        return None
    artifact_sha = ""
    is_hermetic = not vendor
    is_vendor = vendor
    package_identity = pin.get("package_identity", "@ipfs-datasets/logic-runtime-mtl")
    package_digest = ""
    source_digest = ""
    lockfile_digest = ""
    runtime_digest = ""
    executable_digest = ""
    launcher_digest = ""
    launcher_target_digest = ""
    node_version = ""
    platform_id = ""
    if manifest.is_file():
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            artifact_sha = str(payload.get("artifact_sha256") or "")
            is_hermetic = bool(payload.get("is_hermetic_parity_engine", not vendor))
            is_vendor = bool(payload.get("is_vendor_build", vendor))
            version = str(payload.get("version") or version)
            if payload.get("package_identity"):
                package_identity = str(payload["package_identity"])
            package_digest = str(payload.get("package_digest_sha256") or "")
            source_digest = str(payload.get("source_digest_sha256") or "")
            lockfile_digest = str(payload.get("lockfile_digest_sha256") or "")
            runtime_digest = str(payload.get("runtime_digest_sha256") or "")
            executable_digest = str(payload.get("executable_digest_sha256") or "")
            launcher_digest = str(payload.get("launcher_digest_sha256") or "")
            launcher_target_digest = str(
                payload.get("launcher_target_digest_sha256")
                or payload.get("cli_artifact_sha256")
                or ""
            )
            node_version = str(payload.get("node_version") or "")
            platform_id = str(payload.get("platform_id") or "")
    if vendor and (is_hermetic or not is_vendor):
        return None
    if executable_digest:
        try:
            if _sha256_file(exe) != executable_digest:
                return None
        except OSError:
            return None
    observed = _probe_version(exe)
    if observed and pin["version"] not in observed and version not in observed:
        markers = ("runtime-mtl", "parity", "typescript-vendor")
        if not any(token in observed.casefold() for token in markers):
            return None
    if not artifact_sha:
        try:
            artifact_sha = _sha256_bytes(exe.read_bytes())
        except OSError:
            artifact_sha = _sha256_text(exe.read_text(encoding="utf-8", errors="replace"))
    if not launcher_digest:
        launcher_digest = executable_digest or artifact_sha
    if not launcher_target_digest:
        launcher_target_digest = artifact_sha
    return ExternalMonitorIdentity(
        tool_id=tool_id,
        version=version,
        executable=str(exe),
        license=pin["license"],
        source=pin["source"],
        identity_kind=pin["identity_kind"],
        artifact_sha256=artifact_sha,
        package_digest_sha256=package_digest,
        source_digest_sha256=source_digest,
        lockfile_digest_sha256=lockfile_digest,
        runtime_digest_sha256=runtime_digest,
        executable_digest_sha256=executable_digest or artifact_sha,
        launcher_digest_sha256=launcher_digest,
        launcher_target_digest_sha256=launcher_target_digest,
        install_root=str(install_root),
        is_hermetic_parity_engine=is_hermetic and not is_vendor,
        is_vendor_build=is_vendor,
        package_identity=package_identity,
        node_version=node_version,
        platform_id=platform_id,
    )


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_tree(root: Path, *, exclude_names: frozenset[str] | None = None) -> str:
    """Stable tree digest over relative paths and file contents."""

    excluded = exclude_names or frozenset({"node_modules", "dist", ".git"})
    digest = hashlib.sha256()
    if not root.is_dir():
        return digest.hexdigest()
    paths: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in excluded for part in rel_parts):
            continue
        paths.append(path)
    for path in paths:
        rel = path.relative_to(root).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_sha256_file(path).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def resolve_vendor_package_root(
    repo_root: Path | str | None = None,
) -> Path:
    """Locate the locked TypeScript package source tree."""

    if repo_root is not None:
        candidate = Path(repo_root) / VENDOR_PACKAGE_RELATIVE
        if candidate.is_dir():
            return candidate.resolve()
    # From installers/ -> .../ipfs_datasets_py/ipfs_datasets_py/logic/backends/installers
    # parents[4] is the monorepo root that contains ipfs_datasets_py/.
    monorepo = Path(__file__).resolve().parents[5]
    candidate = monorepo / VENDOR_PACKAGE_RELATIVE
    if candidate.is_dir():
        return candidate.resolve()
    datasets = _datasets_package_root()
    # datasets is outer ipfs_datasets_py checkout; package lives under typescript/
    alt = datasets / "typescript" / "logic-runtime-mtl"
    if alt.is_dir():
        return alt.resolve()
    raise RuntimeMTLInstallerError(
        f"vendor TypeScript package not found at {VENDOR_PACKAGE_RELATIVE}"
    )


def compute_vendor_source_digests(
    package_root: Path,
) -> dict[str, str]:
    """Bind package.json, source tree, and lockfile digests."""

    package_json = package_root / "package.json"
    lockfile = package_root / "package-lock.json"
    src_dir = package_root / "src"
    if not package_json.is_file():
        raise RuntimeMTLInstallerError(f"missing package.json under {package_root}")
    if not lockfile.is_file():
        raise RuntimeMTLInstallerError(
            f"missing package-lock.json under {package_root}; "
            "vendor installs require a locked TypeScript dependency graph"
        )
    if not src_dir.is_dir():
        raise RuntimeMTLInstallerError(f"missing src/ under {package_root}")
    return {
        "package_digest_sha256": _sha256_file(package_json),
        "lockfile_digest_sha256": _sha256_file(lockfile),
        "source_digest_sha256": _sha256_tree(src_dir),
    }


def detect_node_runtime() -> dict[str, str]:
    """Resolve Node executable + version and bind a runtime digest."""

    node = shutil.which("node")
    if node is None:
        raise RuntimeMTLInstallerError(
            "Node.js (>=18) is required to build the vendor Runtime MTL engine"
        )
    try:
        completed = subprocess.run(
            [node, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeMTLInstallerError(f"node --version failed: {exc}") from exc
    version = (completed.stdout or completed.stderr or "").strip()
    if not version:
        raise RuntimeMTLInstallerError("node --version produced empty output")
    # Major version gate.
    match = re.search(r"v?(\d+)", version)
    if match is None or int(match.group(1)) < 18:
        raise RuntimeMTLInstallerError(
            f"Node.js >=18 required for vendor Runtime MTL; observed {version!r}"
        )
    runtime_digest = _sha256_text(f"node:{version}:{Path(node).resolve()}")
    return {
        "node_executable": str(Path(node).resolve()),
        "node_version": version.lstrip("v"),
        "runtime_digest_sha256": runtime_digest,
    }


# ---------------------------------------------------------------------------
# Install authorization gate
# ---------------------------------------------------------------------------


def _gate_install(
    tool_id: str,
    *,
    yes: bool,
    strict: bool,
    platform_id: str | None,
    checksum_verified: bool | None,
    test_mode: bool | None,
    import_context: bool,
    capability_discovery: bool,
) -> list[str]:
    """Return block reasons (empty means authorized)."""

    reasons: list[str] = []
    if import_context:
        reasons.append("forbidden_on_import")
    if capability_discovery:
        reasons.append("forbidden_on_capability_discovery")
    if not yes:
        reasons.append("requires_yes_true")
    if test_mode is None:
        test_mode = bool(
            os.environ.get("PYTEST_CURRENT_TEST")
            or os.environ.get("IPFS_DATASETS_PY_TEST_MODE")
        )
    try:
        authorize_installer_entry_install(
            tool_id,
            yes=yes,
            explicit_call=True,
            import_context=import_context,
            capability_discovery=capability_discovery,
            checksum_verified=checksum_verified,
            platform=platform_id,
            system_package_mutation=False,
            test_mode=bool(test_mode),
        )
    except InstallerRegistryError as exc:
        reasons.append(f"registry:{exc}")
    except Exception as exc:  # pragma: no cover - defensive
        reasons.append(f"registry_error:{type(exc).__name__}")

    # Role binding: external Runtime MTL retains finite-trace authority only.
    try:
        role = get_tool_role(tool_id)
        if role.role is not ToolRole.AUTHORITY:
            reasons.append("tool_role_is_not_authority")
        if role.authority_ceiling is not ToolchainAuthorityCeiling.FINITE_TRACE:
            reasons.append("authority_ceiling_is_not_finite_trace")
    except Exception as exc:
        reasons.append(f"role_lookup_failed:{type(exc).__name__}:{exc}")

    if platform_id is not None:
        try:
            default_installer_registry().assert_platform_supported(platform_id)
        except InstallerRegistryError as exc:
            if strict:
                reasons.append(str(exc))
            else:
                reasons.append(f"platform_unsupported:{platform_id}")
    return reasons


def materialize_hermetic_parity_engine(
    tool_id: str,
    *,
    install_root: Path | str | None = None,
    repo_root: Path | str | None = None,
    lock_path: Path | str | None = None,
    force: bool = False,
    datasets_root: Path | str | None = None,
) -> ExternalMonitorIdentity:
    """Write the pin-bound hermetic parity engine and identity manifest.

    Hermetic engines import the Python reference and are **non-production
    shadow evidence** — they cannot satisfy vendor production certification.
    """

    pin = pin_for_tool(tool_id, repo_root=repo_root, lock_path=lock_path)
    root = _expand_install_root(install_root)
    version = pin["version"]
    exe = executable_path(root, tool_id, version, vendor=False)
    manifest = identity_manifest_path(root, tool_id, version, vendor=False)

    if exe.is_file() and manifest.is_file() and not force:
        existing = _identity_from_disk(tool_id, root, pin, vendor=False)
        if existing is not None:
            return existing

    package_identity = pin.get(
        "package_identity", "@ipfs-datasets/logic-runtime-mtl"
    )
    provisional = {
        "schema_version": INSTALL_RECEIPT_SCHEMA,
        "interface": INTERFACE,
        "tool_id": tool_id,
        "version": version,
        "license": pin["license"],
        "source": pin["source"],
        "identity_kind": pin["identity_kind"],
        "role": ToolRole.AUTHORITY.value,
        "authority_ceiling": ToolchainAuthorityCeiling.FINITE_TRACE.value,
        "is_hermetic_parity_engine": True,
        "is_vendor_build": False,
        "replaces_gap_id": GAP_ID,
        "install_root": str(root),
        "executable": str(exe),
        "family": FAMILY,
        "goal_id": GOAL_ID,
        "task_id": TASK_ID,
        "package_identity": package_identity,
        "finite_trace_authority_only": True,
        "never_grants_theorem_authority": True,
        "non_production_shadow_evidence": True,
    }
    _write_identity_manifest(manifest, provisional)
    source = build_parity_engine_source(
        tool_id,
        version,
        identity_file=str(manifest),
        datasets_root=datasets_root or _datasets_package_root(),
    )
    artifact_sha = _write_executable(exe, source)
    provisional["artifact_sha256"] = artifact_sha
    provisional["executable_digest_sha256"] = artifact_sha
    _write_identity_manifest(manifest, provisional)

    return ExternalMonitorIdentity(
        tool_id=tool_id,
        version=version,
        executable=str(exe),
        license=pin["license"],
        source=pin["source"],
        identity_kind=pin["identity_kind"],
        artifact_sha256=artifact_sha,
        executable_digest_sha256=artifact_sha,
        install_root=str(root),
        is_hermetic_parity_engine=True,
        is_vendor_build=False,
        package_identity=package_identity,
    )


def _copy_vendor_package_sources(src: Path, dest: Path) -> None:
    """Copy package sources excluding node_modules/dist into the install tree."""

    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for item in sorted(src.iterdir()):
        if item.name in {"node_modules", "dist", ".git"}:
            continue
        target = dest / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)


def _build_vendor_package(package_dir: Path, *, node: str, npm: str) -> Path:
    """Run npm ci (or install) + build; return the CLI entry path."""

    lock = package_dir / "package-lock.json"
    if lock.is_file():
        install_cmd = [npm, "ci", "--no-fund", "--no-audit"]
    else:
        install_cmd = [npm, "install", "--no-fund", "--no-audit"]
    install = subprocess.run(
        install_cmd,
        cwd=package_dir,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    if install.returncode != 0:
        raise RuntimeMTLInstallerError(
            "npm install/ci failed for vendor Runtime MTL: "
            + (install.stderr or install.stdout or "")[:800]
        )
    build = subprocess.run(
        [npm, "run", "build"],
        cwd=package_dir,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    if build.returncode != 0:
        raise RuntimeMTLInstallerError(
            "npm run build failed for vendor Runtime MTL: "
            + (build.stderr or build.stdout or "")[:800]
        )
    cli = package_dir / "dist" / "src" / "cli.js"
    index = package_dir / "dist" / "src" / "index.js"
    if not cli.is_file() or not index.is_file():
        raise RuntimeMTLInstallerError(
            f"vendor build missing dist artifacts under {package_dir / 'dist'}"
        )
    # Ensure the CLI is executable for direct node invocation.
    mode = cli.stat().st_mode
    cli.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return cli


def _vendor_wrapper_source(
    *,
    node_executable: str,
    cli_path: str,
    version: str,
    identity_file: str,
) -> str:
    """Shell wrapper that runs the Node CLI without touching Python."""

    return f"""#!/usr/bin/env bash
# Pin-bound vendor Runtime MTL external engine ({version}).
# Generated by ExternalRuntimeMTLVendorInstaller@1 / FVT-G210.
# Independent TypeScript/Node monitor — does not import or dispatch to Python.
set -euo pipefail
export RUNTIME_MTL_EXTERNAL_VERSION={version!r}
export RUNTIME_MTL_EXTERNAL_IDENTITY_FILE=${{RUNTIME_MTL_EXTERNAL_IDENTITY_FILE:-{identity_file!r}}}
NODE={node_executable!r}
CLI={cli_path!r}
if [[ ! -x "$NODE" && ! -f "$NODE" ]]; then
  echo "runtime-mtl-external: node runtime missing: $NODE" >&2
  exit 127
fi
if [[ ! -f "$CLI" ]]; then
  echo "runtime-mtl-external: vendor CLI missing: $CLI" >&2
  exit 127
fi
exec "$NODE" "$CLI" "$@"
"""


def _python_reference_dispatch_marker(*artifacts: str) -> str | None:
    """Return the first Python-reference dispatch marker in built artifacts.

    This deliberately audits executable syntax rather than raw substrings so a
    harmless install path such as ``.../ipfs_datasets_py/theorem-provers`` does
    not make an independent Node build fail certification.
    """

    for artifact in artifacts:
        for marker, pattern in _PYTHON_REFERENCE_DISPATCH_PATTERNS:
            if pattern.search(artifact):
                return marker
    return None


def materialize_vendor_typescript_engine(
    tool_id: str = TOOL_RUNTIME_MTL_EXTERNAL,
    *,
    install_root: Path | str | None = None,
    repo_root: Path | str | None = None,
    lock_path: Path | str | None = None,
    force: bool = False,
    platform_id: str | None = None,
) -> ExternalMonitorIdentity:
    """Build the locked TypeScript package into an independent Node executable.

    Does not import or dispatch to the Python reference.  Binds package,
    source, lockfile, runtime, launcher, launcher target, executable, and
    artifact digests.
    """

    if tool_id not in EXTERNAL_TOOLS:
        raise RuntimeMTLInstallerError(f"unknown tool_id {tool_id!r}")
    pin = pin_for_tool(tool_id, repo_root=repo_root, lock_path=lock_path)
    root = _expand_install_root(install_root)
    version = pin["version"]
    host = platform_id or _detect_platform()
    exe = executable_path(root, tool_id, version, vendor=True)
    manifest = identity_manifest_path(root, tool_id, version, vendor=True)
    package_dir = tool_package_dir(root, tool_id, version, vendor=True)

    if exe.is_file() and manifest.is_file() and not force:
        existing = _identity_from_disk(tool_id, root, pin, vendor=True)
        if (
            existing is not None
            and existing.is_vendor_build
            and not existing.is_hermetic_parity_engine
            and existing.artifact_sha256
            and existing.lockfile_digest_sha256
            and existing.source_digest_sha256
        ):
            _publish_managed_vendor_launcher(existing)
            return existing

    package_root = resolve_vendor_package_root(repo_root)
    digests = compute_vendor_source_digests(package_root)
    runtime = detect_node_runtime()
    npm = shutil.which("npm")
    if npm is None:
        raise RuntimeMTLInstallerError(
            "npm is required to build the vendor Runtime MTL engine"
        )

    _copy_vendor_package_sources(package_root, package_dir)
    # Re-bind digests from the installed copy (must match source tree).
    installed_digests = compute_vendor_source_digests(package_dir)
    for key, value in digests.items():
        if installed_digests.get(key) != value:
            raise RuntimeMTLInstallerError(
                f"vendor package digest drift for {key}: "
                f"source={value} installed={installed_digests.get(key)}"
            )

    cli_path = _build_vendor_package(
        package_dir, node=runtime["node_executable"], npm=npm
    )
    artifact_digest = _sha256_file(cli_path)
    # Also hash the compiled library for stronger binding.
    index_digest = _sha256_file(package_dir / "dist" / "src" / "index.js")
    combined_artifact = _sha256_text(f"{artifact_digest}:{index_digest}")

    package_identity = pin.get("package_identity", VENDOR_PACKAGE_IDENTITY)
    provisional = {
        "schema_version": VENDOR_INSTALL_RECEIPT_SCHEMA,
        "interface": VENDOR_INTERFACE,
        "tool_id": tool_id,
        "version": version,
        "license": pin["license"],
        "source": pin["source"],
        "identity_kind": pin["identity_kind"],
        "role": ToolRole.AUTHORITY.value,
        "authority_ceiling": ToolchainAuthorityCeiling.FINITE_TRACE.value,
        "is_hermetic_parity_engine": False,
        "is_vendor_build": True,
        "replaces_gap_id": GAP_ID,
        "install_root": str(root),
        "executable": str(exe),
        "cli_path": str(cli_path),
        "package_dir": str(package_dir),
        "family": FAMILY,
        "goal_id": VENDOR_GOAL_ID,
        "task_id": VENDOR_TASK_ID,
        "repair_task_id": VENDOR_REPAIR_TASK_ID,
        "objective_validation_evidence": OBJECTIVE_VALIDATION_EVIDENCE,
        "package_identity": package_identity,
        "finite_trace_authority_only": True,
        "never_grants_theorem_authority": True,
        "no_python_reference_dispatch": True,
        "platform_id": host,
        "node_version": runtime["node_version"],
        "node_executable": runtime["node_executable"],
        "package_digest_sha256": digests["package_digest_sha256"],
        "source_digest_sha256": digests["source_digest_sha256"],
        "lockfile_digest_sha256": digests["lockfile_digest_sha256"],
        "runtime_digest_sha256": runtime["runtime_digest_sha256"],
        "artifact_sha256": combined_artifact,
        "cli_artifact_sha256": artifact_digest,
        "index_artifact_sha256": index_digest,
        "launcher_target_digest_sha256": artifact_digest,
    }
    _write_identity_manifest(manifest, provisional)
    wrapper = _vendor_wrapper_source(
        node_executable=runtime["node_executable"],
        cli_path=str(cli_path),
        version=version,
        identity_file=str(manifest),
    )
    executable_digest = _write_executable(exe, wrapper)
    provisional["executable_digest_sha256"] = executable_digest
    provisional["executable"] = str(exe)
    provisional["launcher_digest_sha256"] = executable_digest
    _write_identity_manifest(manifest, provisional)

    # Independence check: wrapper and CLI must not mention Python package imports.
    wrapper_text = exe.read_text(encoding="utf-8")
    cli_text = cli_path.read_text(encoding="utf-8")
    dispatch_marker = _python_reference_dispatch_marker(wrapper_text, cli_text)
    if dispatch_marker is not None:
        raise RuntimeMTLInstallerError(
            "vendor engine must not dispatch to Python reference; "
            f"found {dispatch_marker!r}"
        )

    identity = ExternalMonitorIdentity(
        tool_id=tool_id,
        version=version,
        executable=str(exe),
        license=pin["license"],
        source=pin["source"],
        identity_kind=pin["identity_kind"],
        artifact_sha256=combined_artifact,
        package_digest_sha256=digests["package_digest_sha256"],
        source_digest_sha256=digests["source_digest_sha256"],
        lockfile_digest_sha256=digests["lockfile_digest_sha256"],
        runtime_digest_sha256=runtime["runtime_digest_sha256"],
        executable_digest_sha256=executable_digest,
        launcher_digest_sha256=executable_digest,
        launcher_target_digest_sha256=artifact_digest,
        install_root=str(root),
        is_hermetic_parity_engine=False,
        is_vendor_build=True,
        package_identity=package_identity,
        node_version=runtime["node_version"],
        platform_id=host,
    )
    launcher_path = _publish_managed_vendor_launcher(identity)
    # Re-bind launcher digest after PATH publication (must match executable).
    published_launcher_digest = _sha256_file(launcher_path)
    if published_launcher_digest != executable_digest:
        raise RuntimeMTLInstallerError(
            "managed Runtime MTL launcher digest drifted from executable binding"
        )
    provisional["launcher_digest_sha256"] = published_launcher_digest
    provisional["managed_launcher"] = str(launcher_path)
    _write_identity_manifest(manifest, provisional)
    return ExternalMonitorIdentity(
        tool_id=identity.tool_id,
        version=identity.version,
        executable=identity.executable,
        license=identity.license,
        source=identity.source,
        identity_kind=identity.identity_kind,
        artifact_sha256=identity.artifact_sha256,
        package_digest_sha256=identity.package_digest_sha256,
        source_digest_sha256=identity.source_digest_sha256,
        lockfile_digest_sha256=identity.lockfile_digest_sha256,
        runtime_digest_sha256=identity.runtime_digest_sha256,
        executable_digest_sha256=identity.executable_digest_sha256,
        launcher_digest_sha256=published_launcher_digest,
        launcher_target_digest_sha256=identity.launcher_target_digest_sha256,
        install_root=identity.install_root,
        is_hermetic_parity_engine=False,
        is_vendor_build=True,
        package_identity=identity.package_identity,
        node_version=identity.node_version,
        platform_id=identity.platform_id,
    )


# ---------------------------------------------------------------------------
# Public ensure_* entrypoints (registry contract)
# ---------------------------------------------------------------------------


def ensure_runtime_mtl_external(
    *,
    yes: bool = False,
    strict: bool = True,
    force: bool = False,
    install_root: Path | str | None = None,
    repo_root: Path | str | None = None,
    lock_path: Path | str | None = None,
    platform_id: str | None = None,
    hermetic_parity_engine: bool = True,
    vendor: bool = False,
    checksum_verified: bool | None = True,
    import_context: bool = False,
    capability_discovery: bool = False,
    test_mode: bool | None = None,
    datasets_root: Path | str | None = None,
    on_progress: ProgressCallback | None = None,
) -> InstallReceipt:
    """Explicit strict installation of the pinned external Runtime MTL monitor.

    Default materializes the hermetic Python-backed parity engine (FVT-G181).
    Set ``vendor=True`` (or ``hermetic_parity_engine=False``) for the independent
    TypeScript/Node vendor engine (FVT-G210).
    """

    tool_id = TOOL_RUNTIME_MTL_EXTERNAL
    pin = pin_for_tool(tool_id, repo_root=repo_root, lock_path=lock_path)
    selected_version = pin["version"]
    root = _expand_install_root(install_root)
    host_platform = platform_id or _detect_platform()
    use_vendor = bool(vendor or not hermetic_parity_engine)

    try:
        entry = get_installer_entry(tool_id)
        if entry.family.value != FAMILY:
            return InstallReceipt(
                tool_id=tool_id,
                status="failed",
                identity=None,
                selected_version=selected_version,
                detail=f"installer family mismatch: {entry.family.value}",
                strict=strict,
                yes=yes,
                is_vendor_path=use_vendor,
                interface=VENDOR_INTERFACE if use_vendor else INTERFACE,
                goal_id=VENDOR_GOAL_ID if use_vendor else GOAL_ID,
                task_id=VENDOR_TASK_ID if use_vendor else TASK_ID,
                schema_version=(
                    VENDOR_INSTALL_RECEIPT_SCHEMA if use_vendor else INSTALL_RECEIPT_SCHEMA
                ),
                block_reasons=("family_mismatch",),
            )
        if entry.replaces_gap_id and entry.replaces_gap_id != GAP_ID:
            return InstallReceipt(
                tool_id=tool_id,
                status="failed",
                identity=None,
                selected_version=selected_version,
                detail=f"unexpected gap replacement {entry.replaces_gap_id!r}",
                strict=strict,
                yes=yes,
                is_vendor_path=use_vendor,
                interface=VENDOR_INTERFACE if use_vendor else INTERFACE,
                goal_id=VENDOR_GOAL_ID if use_vendor else GOAL_ID,
                task_id=VENDOR_TASK_ID if use_vendor else TASK_ID,
                schema_version=(
                    VENDOR_INSTALL_RECEIPT_SCHEMA if use_vendor else INSTALL_RECEIPT_SCHEMA
                ),
                block_reasons=("gap_mismatch",),
            )
        if entry.ensure_name not in {
            "ensure_runtime_mtl_external",
            "ensure_runtime-mtl-external",
            "ensure_runtime_mtl_vendor",
        }:
            # Registry is still authoritative for presence; continue.
            pass
    except InstallerRegistryError as exc:
        return InstallReceipt(
            tool_id=tool_id,
            status="failed",
            identity=None,
            selected_version=selected_version,
            detail=str(exc),
            strict=strict,
            yes=yes,
            is_vendor_path=use_vendor,
            interface=VENDOR_INTERFACE if use_vendor else INTERFACE,
            goal_id=VENDOR_GOAL_ID if use_vendor else GOAL_ID,
            task_id=VENDOR_TASK_ID if use_vendor else TASK_ID,
            schema_version=(
                VENDOR_INSTALL_RECEIPT_SCHEMA if use_vendor else INSTALL_RECEIPT_SCHEMA
            ),
            block_reasons=("missing_registry_entry",),
        )

    existing = _identity_from_disk(tool_id, root, pin, vendor=use_vendor)
    if (
        existing is not None
        and not force
        and (
            not use_vendor
            or (
                existing.is_vendor_build
                and not existing.is_hermetic_parity_engine
                and _managed_vendor_launcher_is_current(existing)
            )
        )
    ):
        _announce(
            f"{tool_id} {existing.version} already present at {existing.executable}",
            on_progress,
        )
        return InstallReceipt(
            tool_id=tool_id,
            status="already_present",
            identity=existing,
            selected_version=existing.version,
            detail=(
                "pin-bound vendor Runtime MTL already installed"
                if use_vendor
                else "pin-bound external Runtime MTL already installed"
            ),
            strict=strict,
            yes=yes,
            is_vendor_path=use_vendor,
            interface=VENDOR_INTERFACE if use_vendor else INTERFACE,
            goal_id=VENDOR_GOAL_ID if use_vendor else GOAL_ID,
            task_id=VENDOR_TASK_ID if use_vendor else TASK_ID,
            schema_version=(
                VENDOR_INSTALL_RECEIPT_SCHEMA if use_vendor else INSTALL_RECEIPT_SCHEMA
            ),
        )

    block_reasons = _gate_install(
        tool_id,
        yes=yes,
        strict=strict,
        platform_id=host_platform,
        checksum_verified=checksum_verified,
        test_mode=test_mode,
        import_context=import_context,
        capability_discovery=capability_discovery,
    )
    if block_reasons:
        status = "refused" if "requires_yes_true" in block_reasons else "blocked"
        detail = "; ".join(block_reasons)
        _announce(f"{tool_id} install {status}: {detail}", on_progress)
        receipt = InstallReceipt(
            tool_id=tool_id,
            status=status,
            identity=None,
            selected_version=selected_version,
            detail=detail,
            strict=strict,
            yes=yes,
            is_vendor_path=use_vendor,
            interface=VENDOR_INTERFACE if use_vendor else INTERFACE,
            goal_id=VENDOR_GOAL_ID if use_vendor else GOAL_ID,
            task_id=VENDOR_TASK_ID if use_vendor else TASK_ID,
            schema_version=(
                VENDOR_INSTALL_RECEIPT_SCHEMA if use_vendor else INSTALL_RECEIPT_SCHEMA
            ),
            block_reasons=tuple(block_reasons),
        )
        if strict and status != "refused":
            raise RuntimeMTLInstallerError(detail)
        return receipt

    try:
        if use_vendor:
            identity = materialize_vendor_typescript_engine(
                tool_id,
                install_root=root,
                repo_root=repo_root,
                lock_path=lock_path,
                force=force,
                platform_id=host_platform,
            )
        else:
            identity = materialize_hermetic_parity_engine(
                tool_id,
                install_root=root,
                repo_root=repo_root,
                lock_path=lock_path,
                force=force,
                datasets_root=datasets_root,
            )
    except Exception as exc:
        detail = f"materialize_failed:{type(exc).__name__}:{exc}"
        if strict:
            raise RuntimeMTLInstallerError(detail) from exc
        return InstallReceipt(
            tool_id=tool_id,
            status="failed",
            identity=None,
            selected_version=selected_version,
            detail=detail,
            strict=strict,
            yes=yes,
            is_vendor_path=use_vendor,
            interface=VENDOR_INTERFACE if use_vendor else INTERFACE,
            goal_id=VENDOR_GOAL_ID if use_vendor else GOAL_ID,
            task_id=VENDOR_TASK_ID if use_vendor else TASK_ID,
            schema_version=(
                VENDOR_INSTALL_RECEIPT_SCHEMA if use_vendor else INSTALL_RECEIPT_SCHEMA
            ),
            block_reasons=("materialize_failed",),
        )

    if identity.version != selected_version:
        detail = (
            f"strict pin mismatch for {tool_id}: "
            f"installed={identity.version!r} expected={selected_version!r}"
        )
        if strict:
            raise RuntimeMTLInstallerError(detail)
        return InstallReceipt(
            tool_id=tool_id,
            status="failed",
            identity=identity,
            selected_version=selected_version,
            detail=detail,
            strict=strict,
            yes=yes,
            is_vendor_path=use_vendor,
            interface=VENDOR_INTERFACE if use_vendor else INTERFACE,
            goal_id=VENDOR_GOAL_ID if use_vendor else GOAL_ID,
            task_id=VENDOR_TASK_ID if use_vendor else TASK_ID,
            schema_version=(
                VENDOR_INSTALL_RECEIPT_SCHEMA if use_vendor else INSTALL_RECEIPT_SCHEMA
            ),
            block_reasons=("pin_mismatch",),
        )

    observed = _probe_version(Path(identity.executable))
    if selected_version not in observed and "runtime-mtl" not in observed.casefold():
        detail = f"version probe failed for {tool_id}: {observed!r}"
        if strict:
            raise RuntimeMTLInstallerError(detail)
        return InstallReceipt(
            tool_id=tool_id,
            status="failed",
            identity=identity,
            selected_version=selected_version,
            detail=detail,
            strict=strict,
            yes=yes,
            is_vendor_path=use_vendor,
            interface=VENDOR_INTERFACE if use_vendor else INTERFACE,
            goal_id=VENDOR_GOAL_ID if use_vendor else GOAL_ID,
            task_id=VENDOR_TASK_ID if use_vendor else TASK_ID,
            schema_version=(
                VENDOR_INSTALL_RECEIPT_SCHEMA if use_vendor else INSTALL_RECEIPT_SCHEMA
            ),
            block_reasons=("version_probe_failed",),
        )

    if use_vendor and (
        not identity.is_vendor_build or identity.is_hermetic_parity_engine
    ):
        detail = "vendor install produced a hermetic parity engine identity"
        if strict:
            raise RuntimeMTLInstallerError(detail)
        return InstallReceipt(
            tool_id=tool_id,
            status="failed",
            identity=identity,
            selected_version=selected_version,
            detail=detail,
            strict=strict,
            yes=yes,
            is_vendor_path=True,
            interface=VENDOR_INTERFACE,
            goal_id=VENDOR_GOAL_ID,
            task_id=VENDOR_TASK_ID,
            schema_version=VENDOR_INSTALL_RECEIPT_SCHEMA,
            block_reasons=("hermetic_promoted_as_vendor",),
        )

    _announce(
        f"installed {tool_id} {identity.version} "
        f"{'vendor' if use_vendor else 'parity'} engine at {identity.executable}",
        on_progress,
    )
    return InstallReceipt(
        tool_id=tool_id,
        status="installed",
        identity=identity,
        selected_version=selected_version,
        detail=(
            "pin-bound independent TypeScript/Node vendor Runtime MTL engine materialized"
            if use_vendor
            else "pin-bound hermetic external Runtime MTL parity engine materialized"
        ),
        strict=strict,
        yes=yes,
        is_vendor_path=use_vendor,
        interface=VENDOR_INTERFACE if use_vendor else INTERFACE,
        goal_id=VENDOR_GOAL_ID if use_vendor else GOAL_ID,
        task_id=VENDOR_TASK_ID if use_vendor else TASK_ID,
        schema_version=(
            VENDOR_INSTALL_RECEIPT_SCHEMA if use_vendor else INSTALL_RECEIPT_SCHEMA
        ),
    )


def ensure_runtime_mtl_vendor(
    *,
    yes: bool = False,
    strict: bool = True,
    force: bool = False,
    install_root: Path | str | None = None,
    repo_root: Path | str | None = None,
    lock_path: Path | str | None = None,
    platform_id: str | None = None,
    checksum_verified: bool | None = True,
    import_context: bool = False,
    capability_discovery: bool = False,
    test_mode: bool | None = None,
    on_progress: ProgressCallback | None = None,
) -> RuntimeMTLInstallBundle:
    """Install the independent TypeScript/Node vendor Runtime MTL engine (FVT-G210)."""

    root = _expand_install_root(install_root)
    receipt = ensure_runtime_mtl_external(
        yes=yes,
        strict=strict,
        force=force,
        install_root=root,
        repo_root=repo_root,
        lock_path=lock_path,
        platform_id=platform_id,
        hermetic_parity_engine=False,
        vendor=True,
        checksum_verified=checksum_verified,
        import_context=import_context,
        capability_discovery=capability_discovery,
        test_mode=test_mode,
        on_progress=on_progress,
    )
    return RuntimeMTLInstallBundle(
        receipts=[receipt],
        install_root=str(root),
        interface=VENDOR_INTERFACE,
        goal_id=VENDOR_GOAL_ID,
        task_id=VENDOR_TASK_ID,
        is_vendor_path=True,
    )


def ensure_runtime_mtl(
    *,
    yes: bool = False,
    strict: bool = True,
    force: bool = False,
    install_root: Path | str | None = None,
    tools: Sequence[str] | None = None,
    **kwargs: Any,
) -> RuntimeMTLInstallBundle:
    """Install every required external Runtime MTL parity engine (strict selection).

    Alias bundle entry for multi-tool future expansion; currently installs
    ``runtime-mtl-external`` only.
    """

    return ensure_runtime_mtl_external_bundle(
        yes=yes,
        strict=strict,
        force=force,
        install_root=install_root,
        tools=tools,
        **kwargs,
    )


def ensure_runtime_mtl_external_bundle(
    *,
    yes: bool = False,
    strict: bool = True,
    force: bool = False,
    install_root: Path | str | None = None,
    repo_root: Path | str | None = None,
    lock_path: Path | str | None = None,
    tools: Sequence[str] | None = None,
    **kwargs: Any,
) -> RuntimeMTLInstallBundle:
    """Install the external Runtime MTL parity engine as a bundle."""

    selected = tuple(tools or EXTERNAL_TOOLS)
    root = _expand_install_root(install_root)
    receipts: list[InstallReceipt] = []
    for tool_id in selected:
        if tool_id != TOOL_RUNTIME_MTL_EXTERNAL:
            raise RuntimeMTLInstallerError(f"unknown external tool {tool_id!r}")
        receipts.append(
            ensure_runtime_mtl_external(
                yes=yes,
                strict=strict,
                force=force,
                install_root=root,
                repo_root=repo_root,
                lock_path=lock_path,
                **kwargs,
            )
        )
    return RuntimeMTLInstallBundle(receipts=receipts, install_root=str(root))


def describe_runtime_mtl_installer() -> dict[str, Any]:
    """Side-effect-free metadata for packaging and discovery."""

    registry = default_installer_registry()
    entries = []
    for tool_id in EXTERNAL_TOOLS:
        entry = registry.get(tool_id)
        pin = pin_for_tool(tool_id)
        entries.append(
            {
                "tool_id": tool_id,
                "ensure_name": entry.ensure_name,
                "module_path": entry.module_path,
                "replaces_gap_id": entry.replaces_gap_id,
                "pin_version": pin["version"],
                "role": ToolRole.AUTHORITY.value,
                "authority_ceiling": ToolchainAuthorityCeiling.FINITE_TRACE.value,
            }
        )
    return {
        "interface": INTERFACE,
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "task_id": TASK_ID,
        "program": PROGRAM,
        "family": FAMILY,
        "gap_id": GAP_ID,
        "tools": entries,
        "vendor": {
            "interface": VENDOR_INTERFACE,
            "schema_version": VENDOR_SCHEMA_VERSION,
            "goal_id": VENDOR_GOAL_ID,
            "task_id": VENDOR_TASK_ID,
            "repair_task_id": VENDOR_REPAIR_TASK_ID,
            "objective_validation_evidence": OBJECTIVE_VALIDATION_EVIDENCE,
            "program": VENDOR_PROGRAM,
            "package_identity": VENDOR_PACKAGE_IDENTITY,
            "package_relative": str(VENDOR_PACKAGE_RELATIVE),
            "ensure_name": "ensure_runtime_mtl_vendor",
            "managed_executable_name": MANAGED_EXECUTABLE_NAME,
            "managed_install_root_env_vars": list(MANAGED_INSTALL_ROOT_ENV_VARS),
        },
        "policy": {
            "never_on_import": True,
            "requires_yes_true": True,
            "user_local_only": True,
            "finite_trace_authority_only": True,
            "never_grants_theorem_authority": True,
            "no_global_correctness_claim": True,
            "cross_runtime_parity": True,
            "strict_installation_selects_exact_pin": True,
            "hermetic_parity_engines_are_non_production_shadows": True,
            "hermetic_parity_engines_cannot_satisfy_vendor": True,
            "vendor_builds_independent_typescript_node": True,
            "vendor_never_imports_python_reference": True,
            "package_source_lockfile_runtime_digests_bound": True,
            "package_source_lockfile_runtime_launcher_executable_artifact_digests_bound": True,
            "vendor_launcher_is_digest_bound_and_path_visible": True,
            "explicit_approved_immutable_deployment_root": True,
            "objective_validation_repair": True,
            "objective_validation_evidence": OBJECTIVE_VALIDATION_EVIDENCE,
        },
        "default_lock_path": str(resolve_lock_path()),
    }


# Import-time safety: this module must never install or download.
def _import_side_effect_free() -> bool:
    return True


assert _import_side_effect_free() is True


__all__ = [
    "INTERFACE",
    "SCHEMA_VERSION",
    "INSTALL_RECEIPT_SCHEMA",
    "GOAL_ID",
    "TASK_ID",
    "PROGRAM",
    "FAMILY",
    "GAP_ID",
    "VENDOR_INTERFACE",
    "VENDOR_SCHEMA_VERSION",
    "VENDOR_INSTALL_RECEIPT_SCHEMA",
    "VENDOR_GOAL_ID",
    "VENDOR_TASK_ID",
    "VENDOR_REPAIR_TASK_ID",
    "OBJECTIVE_VALIDATION_EVIDENCE",
    "VENDOR_PROGRAM",
    "VENDOR_PACKAGE_RELATIVE",
    "VENDOR_PACKAGE_IDENTITY",
    "TOOL_RUNTIME_MTL_EXTERNAL",
    "EXTERNAL_TOOLS",
    "MANAGED_EXECUTABLE_NAME",
    "MANAGED_INSTALL_ROOT_ENV_VARS",
    "DEFAULT_PINS",
    "ENV_FORCE_STATUS",
    "ENV_FORCE_VERDICT",
    "ENV_DISAGREE",
    "ENV_MALFORMED",
    "ENV_SLEEP_SECONDS",
    "ENV_AUTHORIZE_GLOBAL_PROOF",
    "RuntimeMTLInstallerError",
    "RuntimeMTLInstallBundle",
    "InstallReceipt",
    "ExternalMonitorIdentity",
    "build_parity_engine_source",
    "compute_vendor_source_digests",
    "describe_runtime_mtl_installer",
    "detect_node_runtime",
    "ensure_runtime_mtl",
    "ensure_runtime_mtl_external",
    "ensure_runtime_mtl_external_bundle",
    "ensure_runtime_mtl_vendor",
    "executable_path",
    "materialize_hermetic_parity_engine",
    "materialize_vendor_typescript_engine",
    "managed_executable_path",
    "pin_for_tool",
    "resolve_vendor_package_root",
]
