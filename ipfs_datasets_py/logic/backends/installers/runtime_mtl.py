"""External Runtime MTL parity-engine installer plugin.

``RuntimeMTLExternalInstaller@1`` / FVT-G181 (FVT-052).

Replaces the declared ``runtime_mtl_external`` gap with a pin-bound external
monitor that participates in cross-runtime semantic disagreement checks.
Installation is fail-closed: requires explicit ``yes=True``, never runs on
import or capability discovery, and is user-local only.

Managed pins come from ``FormalVerificationDeploymentLock@2`` /
``FormalVerificationInstallerRegistry@1`` (tool id ``runtime-mtl-external``).

When a real vendor binary is unavailable offline, ``ensure_runtime_mtl_external``
materializes a pin-bound **hermetic parity engine** that speaks the portable
``RuntimeMTLMonitor@1`` evaluate-case JSON contract.  The hermetic engine is
process-isolated and supports certification controls for disagreement,
malformed output, and timeout probes.  Authority remains finite-trace monitor
only — never theorem / global correctness.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import stat
import sys
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

TOOL_RUNTIME_MTL_EXTERNAL: Final = "runtime-mtl-external"
EXTERNAL_TOOLS: Final = (TOOL_RUNTIME_MTL_EXTERNAL,)
EXECUTABLE_NAME: Final = "runtime-mtl-external"

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

# Environment controls understood by hermetic parity engine (certification only).
ENV_FORCE_STATUS: Final = "RUNTIME_MTL_EXTERNAL_FORCE_STATUS"
ENV_FORCE_VERDICT: Final = "RUNTIME_MTL_EXTERNAL_FORCE_VERDICT"
ENV_DISAGREE: Final = "RUNTIME_MTL_EXTERNAL_DISAGREE"
ENV_MALFORMED: Final = "RUNTIME_MTL_EXTERNAL_MALFORMED"
ENV_SLEEP_SECONDS: Final = "RUNTIME_MTL_EXTERNAL_SLEEP_SECONDS"
ENV_IDENTITY_FILE: Final = "RUNTIME_MTL_EXTERNAL_IDENTITY_FILE"
ENV_AUTHORIZE_GLOBAL_PROOF: Final = "RUNTIME_MTL_EXTERNAL_AUTHORIZE_GLOBAL_PROOF"

ProgressCallback = Callable[[str], None]


class RuntimeMTLInstallerError(ValueError):
    """Raised when external Runtime MTL installation is refused or invalid."""


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExternalMonitorIdentity:
    """Exact pin-bound identity of the external Runtime MTL parity engine."""

    tool_id: str
    version: str
    executable: str
    license: str
    source: str
    identity_kind: str
    role: str = ToolRole.AUTHORITY.value
    authority_ceiling: str = ToolchainAuthorityCeiling.FINITE_TRACE.value
    is_hermetic_parity_engine: bool = True
    artifact_sha256: str = ""
    install_root: str = ""
    replaces_gap_id: str = GAP_ID
    package_identity: str = "@ipfs-datasets/logic-runtime-mtl"

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_sha256": self.artifact_sha256,
            "authority_ceiling": self.authority_ceiling,
            "executable": self.executable,
            "identity_kind": self.identity_kind,
            "install_root": self.install_root,
            "is_hermetic_parity_engine": self.is_hermetic_parity_engine,
            "license": self.license,
            "package_identity": self.package_identity,
            "replaces_gap_id": self.replaces_gap_id,
            "role": self.role,
            "source": self.source,
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
        if self.schema_version != INSTALL_RECEIPT_SCHEMA:
            raise RuntimeMTLInstallerError(
                f"install receipt schema must be {INSTALL_RECEIPT_SCHEMA}"
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
    """Combined install result for the external Runtime MTL parity engine."""

    receipts: list[InstallReceipt] = field(default_factory=list)
    install_root: str = ""
    gap_replaced: str = GAP_ID
    interface: str = INTERFACE
    goal_id: str = GOAL_ID
    task_id: str = TASK_ID

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
    if install_root is None:
        raw = os.environ.get(
            "IPFS_DATASETS_PY_THEOREM_PROVERS_ROOT",
            DEFAULT_USER_LOCAL_INSTALL_ROOT,
        )
    else:
        raw = str(install_root)
    return Path(os.path.expanduser(raw)).resolve()


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


def tool_bin_dir(install_root: Path, tool_id: str, version: str) -> Path:
    return install_root / "runtime-mtl-external" / tool_id / version / "bin"


def identity_manifest_path(install_root: Path, tool_id: str, version: str) -> Path:
    return (
        install_root
        / "runtime-mtl-external"
        / tool_id
        / version
        / "identity.json"
    )


def executable_path(install_root: Path, tool_id: str, version: str) -> Path:
    return tool_bin_dir(install_root, tool_id, version) / EXECUTABLE_NAME


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
) -> ExternalMonitorIdentity | None:
    version = pin["version"]
    exe = executable_path(install_root, tool_id, version)
    manifest = identity_manifest_path(install_root, tool_id, version)
    if not exe.is_file():
        return None
    artifact_sha = ""
    is_hermetic = True
    package_identity = pin.get("package_identity", "@ipfs-datasets/logic-runtime-mtl")
    if manifest.is_file():
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            artifact_sha = str(payload.get("artifact_sha256") or "")
            is_hermetic = bool(payload.get("is_hermetic_parity_engine", True))
            version = str(payload.get("version") or version)
            if payload.get("package_identity"):
                package_identity = str(payload["package_identity"])
    observed = _probe_version(exe)
    if observed and pin["version"] not in observed and version not in observed:
        if "runtime-mtl" not in observed.casefold() and "parity" not in observed.casefold():
            return None
    return ExternalMonitorIdentity(
        tool_id=tool_id,
        version=version,
        executable=str(exe),
        license=pin["license"],
        source=pin["source"],
        identity_kind=pin["identity_kind"],
        artifact_sha256=artifact_sha or _sha256_text(exe.read_text(encoding="utf-8")),
        install_root=str(install_root),
        is_hermetic_parity_engine=is_hermetic,
        package_identity=package_identity,
    )


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
    """Write the pin-bound hermetic parity engine and identity manifest."""

    pin = pin_for_tool(tool_id, repo_root=repo_root, lock_path=lock_path)
    root = _expand_install_root(install_root)
    version = pin["version"]
    exe = executable_path(root, tool_id, version)
    manifest = identity_manifest_path(root, tool_id, version)

    if exe.is_file() and manifest.is_file() and not force:
        existing = _identity_from_disk(tool_id, root, pin)
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
        "replaces_gap_id": GAP_ID,
        "install_root": str(root),
        "executable": str(exe),
        "family": FAMILY,
        "goal_id": GOAL_ID,
        "task_id": TASK_ID,
        "package_identity": package_identity,
        "finite_trace_authority_only": True,
        "never_grants_theorem_authority": True,
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
    _write_identity_manifest(manifest, provisional)

    return ExternalMonitorIdentity(
        tool_id=tool_id,
        version=version,
        executable=str(exe),
        license=pin["license"],
        source=pin["source"],
        identity_kind=pin["identity_kind"],
        artifact_sha256=artifact_sha,
        install_root=str(root),
        is_hermetic_parity_engine=True,
        package_identity=package_identity,
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
    checksum_verified: bool | None = True,
    import_context: bool = False,
    capability_discovery: bool = False,
    test_mode: bool | None = None,
    datasets_root: Path | str | None = None,
    on_progress: ProgressCallback | None = None,
) -> InstallReceipt:
    """Explicit strict installation of the pinned external Runtime MTL monitor."""

    tool_id = TOOL_RUNTIME_MTL_EXTERNAL
    pin = pin_for_tool(tool_id, repo_root=repo_root, lock_path=lock_path)
    selected_version = pin["version"]
    root = _expand_install_root(install_root)
    host_platform = platform_id or _detect_platform()

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
                block_reasons=("gap_mismatch",),
            )
        if entry.ensure_name not in {
            "ensure_runtime_mtl_external",
            "ensure_runtime-mtl-external",
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
            block_reasons=("missing_registry_entry",),
        )

    existing = _identity_from_disk(tool_id, root, pin)
    if existing is not None and not force:
        _announce(
            f"{tool_id} {existing.version} already present at {existing.executable}",
            on_progress,
        )
        return InstallReceipt(
            tool_id=tool_id,
            status="already_present",
            identity=existing,
            selected_version=existing.version,
            detail="pin-bound external Runtime MTL already installed",
            strict=strict,
            yes=yes,
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
            block_reasons=tuple(block_reasons),
        )
        if strict and status != "refused":
            raise RuntimeMTLInstallerError(detail)
        return receipt

    if not hermetic_parity_engine:
        detail = (
            "real vendor binary acquisition is not performed in offline "
            "certification lanes; set hermetic_parity_engine=True for pin-bound engines"
        )
        if strict:
            raise RuntimeMTLInstallerError(detail)
        return InstallReceipt(
            tool_id=tool_id,
            status="failed",
            identity=None,
            selected_version=selected_version,
            detail=detail,
            strict=strict,
            yes=yes,
            block_reasons=("vendor_binary_unavailable_offline",),
        )

    try:
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
            block_reasons=("version_probe_failed",),
        )

    _announce(
        f"installed {tool_id} {identity.version} parity engine at {identity.executable}",
        on_progress,
    )
    return InstallReceipt(
        tool_id=tool_id,
        status="installed",
        identity=identity,
        selected_version=selected_version,
        detail="pin-bound hermetic external Runtime MTL parity engine materialized",
        strict=strict,
        yes=yes,
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
        "policy": {
            "never_on_import": True,
            "requires_yes_true": True,
            "user_local_only": True,
            "finite_trace_authority_only": True,
            "never_grants_theorem_authority": True,
            "no_global_correctness_claim": True,
            "cross_runtime_parity": True,
            "strict_installation_selects_exact_pin": True,
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
    "TOOL_RUNTIME_MTL_EXTERNAL",
    "EXTERNAL_TOOLS",
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
    "describe_runtime_mtl_installer",
    "ensure_runtime_mtl",
    "ensure_runtime_mtl_external",
    "ensure_runtime_mtl_external_bundle",
    "executable_path",
    "materialize_hermetic_parity_engine",
    "pin_for_tool",
]
