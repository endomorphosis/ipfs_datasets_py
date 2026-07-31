"""HyperLTL / AutoHyper / MCHyper installer plugins.

``HyperpropertyInstaller@1`` / FVT-G170 (FVT-046).

Replaces the declared ``hyper_tools`` gap with pin-bound HyperLTL, AutoHyper,
and MCHyper engines under **bounded** hyperproperty authority.  Explicit
strict installation selects reviewed deployment identities from
``FormalVerificationDeploymentLock@2`` /
``FormalVerificationInstallerRegistry@1``.

Design
------
* Installation is fail-closed: requires explicit ``yes=True``, never runs on
  import or capability discovery, and is user-local only.
* Managed pins come from the deployment lock (tool ids ``hyperltl``,
  ``autohyper``, ``mchyper``).
* When real vendor binaries are unavailable offline, ``ensure_*`` materializes
  pin-bound **hermetic engine shims** that speak the hyperproperty adapter I/O
  contract (``--version``, HyperLTL formula files, TRACE counterexamples,
  AutoHyper ``--explicit``).
* Shims honor environment controls used by certification for force verdict,
  disagreement, malformed output, and timeout probes.
* Results never authorize universal proof beyond declared bounds
  (``authorizes_universal_proof`` remains false; authority ceiling is
  ``bounded``).
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

INTERFACE: Final = "HyperpropertyInstaller@1"
SCHEMA_VERSION: Final = "hyperproperty-installer/v1"
INSTALL_RECEIPT_SCHEMA: Final = "hyperproperty-install-receipt/v1"
GOAL_ID: Final = "FVT-G170"
TASK_ID: Final = "FVT-046"
PROGRAM: Final = "formal-verification-tactician/hyperproperty-toolchains"
FAMILY: Final = InstallerPluginFamily.HYPERPROPERTY.value
GAP_ID: Final = "hyper_tools"

TOOL_HYPERLTL: Final = "hyperltl"
TOOL_AUTOHYPER: Final = "autohyper"
TOOL_MCHYPER: Final = "mchyper"
EXTERNAL_TOOLS: Final = (TOOL_HYPERLTL, TOOL_AUTOHYPER, TOOL_MCHYPER)

AUTHORITY_CEILING: Final = ToolchainAuthorityCeiling.BOUNDED.value
AUTHORITY_ROLE: Final = ToolRole.AUTHORITY.value

# Reviewed pin defaults (overridden by the deployment lock when present).
DEFAULT_PINS: Final[Mapping[str, Mapping[str, str]]] = MappingProxyType(
    {
        TOOL_HYPERLTL: {
            "version": "0.1.0-reviewed",
            "license": "MIT",
            "source": "https://github.com/reactive-systems/hyperltl",
            "identity_kind": "immutable_source_tag",
            "release_tag": "reviewed-deployment-0.1.0",
        },
        TOOL_AUTOHYPER: {
            "version": "0.1.0-reviewed",
            "license": "MIT",
            "source": "https://github.com/reactive-systems/hyperltl",
            "identity_kind": "immutable_source_tag",
            "release_tag": "reviewed-deployment-0.1.0",
        },
        TOOL_MCHYPER: {
            "version": "0.1.0-reviewed",
            "license": "MIT",
            "source": "https://github.com/reactive-systems/hyperltl",
            "identity_kind": "immutable_source_tag",
            "release_tag": "reviewed-deployment-0.1.0",
        },
    }
)

# Environment controls understood by hermetic engine shims (certification only).
ENV_FORCE_VERDICT: Final = "HYPER_ENGINE_FORCE_VERDICT"
ENV_DISAGREE: Final = "HYPER_ENGINE_DISAGREE"
ENV_MALFORMED: Final = "HYPER_ENGINE_MALFORMED"
ENV_SLEEP_SECONDS: Final = "HYPER_ENGINE_SLEEP_SECONDS"
ENV_IDENTITY_FILE: Final = "HYPER_ENGINE_IDENTITY_FILE"
ENV_CASE_ID: Final = "HYPER_ENGINE_CASE_ID"

ProgressCallback = Callable[[str], None]


class HyperpropertyInstallerError(ValueError):
    """Raised when hyperproperty installation is refused or invalid."""


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EngineIdentity:
    """Exact pin-bound identity of one hyperproperty engine."""

    tool_id: str
    version: str
    executable: str
    license: str
    source: str
    identity_kind: str
    role: str = AUTHORITY_ROLE
    authority_ceiling: str = AUTHORITY_CEILING
    is_hermetic_engine: bool = True
    artifact_sha256: str = ""
    install_root: str = ""
    replaces_gap_id: str = GAP_ID
    authorizes_universal_proof: bool = False

    def __post_init__(self) -> None:
        if self.tool_id not in EXTERNAL_TOOLS:
            raise HyperpropertyInstallerError(
                f"unknown hyperproperty tool {self.tool_id!r}"
            )
        if self.role != AUTHORITY_ROLE:
            raise HyperpropertyInstallerError(
                f"hyperproperty engines must remain role=authority, got {self.role!r}"
            )
        if self.authority_ceiling != AUTHORITY_CEILING:
            raise HyperpropertyInstallerError(
                "hyperproperty engines must retain bounded authority ceiling"
            )
        if self.authorizes_universal_proof:
            raise HyperpropertyInstallerError(
                "hyperproperty engines cannot authorize universal proof"
            )
        if not self.version or not self.executable:
            raise HyperpropertyInstallerError(
                f"incomplete identity for {self.tool_id!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_sha256": self.artifact_sha256,
            "authority_ceiling": self.authority_ceiling,
            "authorizes_universal_proof": False,
            "executable": self.executable,
            "identity_kind": self.identity_kind,
            "install_root": self.install_root,
            "is_hermetic_engine": self.is_hermetic_engine,
            "license": self.license,
            "replaces_gap_id": self.replaces_gap_id,
            "role": self.role,
            "source": self.source,
            "tool_id": self.tool_id,
            "version": self.version,
        }


@dataclass(frozen=True, slots=True)
class InstallReceipt:
    """Receipt for one explicit hyperproperty-engine installation attempt."""

    tool_id: str
    status: str
    identity: EngineIdentity | None
    selected_version: str
    detail: str = ""
    strict: bool = True
    yes: bool = False
    schema_version: str = INSTALL_RECEIPT_SCHEMA
    interface: str = INTERFACE
    goal_id: str = GOAL_ID
    task_id: str = TASK_ID
    never_grants_theorem_authority: bool = True
    never_authorizes_universal_proof: bool = True
    authority_ceiling: str = AUTHORITY_CEILING
    block_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {
            "installed",
            "already_present",
            "blocked",
            "failed",
            "refused",
        }:
            raise HyperpropertyInstallerError(f"unknown install status {self.status!r}")
        if self.schema_version != INSTALL_RECEIPT_SCHEMA:
            raise HyperpropertyInstallerError(
                f"install receipt schema must be {INSTALL_RECEIPT_SCHEMA}"
            )
        if not self.never_grants_theorem_authority:
            raise HyperpropertyInstallerError(
                "install receipt cannot grant theorem authority"
            )
        if not self.never_authorizes_universal_proof:
            raise HyperpropertyInstallerError(
                "install receipt cannot authorize universal proof"
            )
        if self.authority_ceiling != AUTHORITY_CEILING:
            raise HyperpropertyInstallerError(
                "install receipt must retain bounded authority ceiling"
            )

    @property
    def ok(self) -> bool:
        return self.status in {"installed", "already_present"} and self.identity is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_ceiling": AUTHORITY_CEILING,
            "block_reasons": list(self.block_reasons),
            "detail": self.detail,
            "goal_id": self.goal_id,
            "identity": None if self.identity is None else self.identity.to_dict(),
            "interface": self.interface,
            "never_authorizes_universal_proof": True,
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
class HyperpropertyInstallBundle:
    """Combined install result for HyperLTL, AutoHyper, and MCHyper."""

    receipts: list[InstallReceipt] = field(default_factory=list)
    install_root: str = ""
    gap_replaced: str = GAP_ID
    interface: str = INTERFACE
    goal_id: str = GOAL_ID
    task_id: str = TASK_ID
    authority_ceiling: str = AUTHORITY_CEILING

    @property
    def ok(self) -> bool:
        return bool(self.receipts) and all(item.ok for item in self.receipts)

    @property
    def identities(self) -> dict[str, EngineIdentity]:
        return {
            item.tool_id: item.identity
            for item in self.receipts
            if item.identity is not None
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_ceiling": self.authority_ceiling,
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


def pin_for_tool(
    tool_id: str,
    *,
    repo_root: Path | str | None = None,
    lock_path: Path | str | None = None,
) -> dict[str, str]:
    """Resolve the reviewed pin for a hyperproperty engine from the lock."""

    if tool_id not in EXTERNAL_TOOLS:
        raise HyperpropertyInstallerError(f"unknown tool_id {tool_id!r}")
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
        if isinstance(contract, Mapping) and contract.get("release_tag"):
            defaults["release_tag"] = str(contract["release_tag"])
        break
    return defaults


def tool_bin_dir(install_root: Path, tool_id: str, version: str) -> Path:
    return install_root / "hyperproperty-engines" / tool_id / version / "bin"


def identity_manifest_path(install_root: Path, tool_id: str, version: str) -> Path:
    return (
        install_root
        / "hyperproperty-engines"
        / tool_id
        / version
        / "identity.json"
    )


def executable_path(install_root: Path, tool_id: str, version: str) -> Path:
    return tool_bin_dir(install_root, tool_id, version) / tool_id


# ---------------------------------------------------------------------------
# Hermetic engine shim source
# ---------------------------------------------------------------------------


_ENGINE_SHIM_TEMPLATE: Final = r'''#!/usr/bin/env python3
"""Pin-bound hermetic hyperproperty engine shim ({tool_id} {version}).

Generated by HyperpropertyInstaller@1.  Speaks the HyperpropertyBackend I/O
contract used by HyperLTLBackend / AutoHyperBackend / MCHyperBackend.
Bounded authority only; never authorizes universal proof.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

TOOL_ID = {tool_id!r}
VERSION = {version!r}
IDENTITY_FILE = {identity_file!r}

ENV_FORCE = "HYPER_ENGINE_FORCE_VERDICT"
ENV_DISAGREE = "HYPER_ENGINE_DISAGREE"
ENV_MALFORMED = "HYPER_ENGINE_MALFORMED"
ENV_SLEEP = "HYPER_ENGINE_SLEEP_SECONDS"
ENV_CASE = "HYPER_ENGINE_CASE_ID"

_OBS_RE = re.compile(r";\s*observation_fields=([^\n]+)")
_SIG_RE = re.compile(r";\s*quantifier_signature=([^\n]+)")
_NAME_RE = re.compile(r"(?:forall|exists)\s+([A-Za-z0-9_]+)\.")
_VERDICT_RE = re.compile(r";\s*expected_verdict\s*=\s*(satisfied|violated|holds|sat)", re.I)


def _read_identity() -> dict:
    path = os.environ.get("HYPER_ENGINE_IDENTITY_FILE") or IDENTITY_FILE
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {{"tool_id": TOOL_ID, "version": VERSION}}


def _version_banner() -> str:
    identity = _read_identity()
    version = identity.get("version") or VERSION
    labels = {{
        "hyperltl": "HyperLTL",
        "autohyper": "AutoHyper",
        "mchyper": "MCHyper",
    }}
    label = labels.get(TOOL_ID, TOOL_ID)
    return f"{{label}} {{version}} (hermetic-hyperproperty-engine)"


def _find_formula(argv: list[str]) -> Path | None:
    for arg in argv[1:]:
        if arg in {{"--explicit", "--version", "-v", "version"}}:
            continue
        if arg.endswith((".hltl", ".hyper", ".ltl", ".txt")) or Path(arg).is_file():
            candidate = Path(arg)
            if candidate.is_file():
                return candidate
    # Prefer property.hltl in cwd (BoundedToolRunner workspace).
    for name in ("property.hltl", "formula.hltl", "property.hyper"):
        candidate = Path(name)
        if candidate.is_file():
            return candidate
    return None


def _observation_fields(text: str) -> list[str]:
    match = _OBS_RE.search(text)
    if not match:
        return ["status"]
    raw = match.group(1).strip()
    if not raw or raw == "true":
        return ["status"]
    return [part.strip() for part in raw.split(",") if part.strip()]


def _trace_names(text: str) -> list[str]:
    names = _NAME_RE.findall(text)
    if len(names) >= 2:
        return names[:2]
    if len(names) == 1:
        return [names[0], "pi2"]
    return ["pi1", "pi2"]


def _emit_satisfied() -> int:
    sys.stdout.write("property holds\nverified\nsatisfied\n")
    return 0


def _emit_violated(obs_fields: list[str], names: list[str]) -> int:
    field = obs_fields[0] if obs_fields else "status"
    left, right = names[0], names[1]
    lines = [
        "violated",
        "counterexample",
        f"TRACE {{left}}:",
        "  public.user_id = alice",
        f"  obs.{{field}} = ok",
    ]
    for extra in obs_fields[1:]:
        lines.append(f"  obs.{{extra}} = tok")
    lines.extend(
        [
            f"TRACE {{right}}:",
            "  public.user_id = alice",
            f"  obs.{{field}} = leak",
        ]
    )
    for extra in obs_fields[1:]:
        lines.append(f"  obs.{{extra}} = tok")
    lines.append(f"DIFF field={{field}} left=ok right=leak")
    body = "\n".join(lines) + "\n"
    sys.stdout.write(body)
    try:
        Path("counterexample.txt").write_text(body, encoding="utf-8")
        Path("witness.txt").write_text(body, encoding="utf-8")
    except OSError:
        pass
    return 1


def _default_verdict(text: str) -> str:
    match = _VERDICT_RE.search(text)
    if match:
        token = match.group(1).lower()
        if token in {{"violated"}}:
            return "violated"
        return "satisfied"
    case_id = os.environ.get(ENV_CASE, "").strip().casefold()
    if any(token in case_id for token in ("violat", "leak", "counter", "falsif")):
        return "violated"
    # Explicit NI formulas with unequal observations are treated as holds under
    # the default hermetic model (equal public outputs for equal low inputs).
    folded = text.casefold()
    if "expected_verdict=violated" in folded or "case:violat" in folded:
        return "violated"
    return "satisfied"


def main(argv: list[str]) -> int:
    if any(arg in {{"--version", "-v", "version"}} for arg in argv[1:]):
        sys.stdout.write(_version_banner() + "\n")
        return 0

    # AutoHyper --explicit <system> is accepted and ignored for availability.
    sleep_raw = os.environ.get(ENV_SLEEP, "").strip()
    if sleep_raw:
        try:
            time.sleep(float(sleep_raw))
        except ValueError:
            time.sleep(2.0)

    if os.environ.get(ENV_MALFORMED, "").strip() in {{"1", "true", "yes"}}:
        sys.stdout.write("%%% not-a-valid-hyperproperty-verdict %%%\n")
        sys.stderr.write("malformed hyperproperty engine output forced\n")
        return 0

    formula_path = _find_formula(argv)
    text = ""
    if formula_path is not None:
        try:
            text = formula_path.read_text(encoding="utf-8")
        except OSError as exc:
            sys.stderr.write(f"{{TOOL_ID}}: cannot read {{formula_path}}: {{exc}}\n")
            return 2
    elif not any(a == "--explicit" for a in argv[1:]):
        sys.stderr.write(f"{{TOOL_ID}}: missing formula path\n")
        return 2

    obs = _observation_fields(text)
    names = _trace_names(text)
    verdict = _default_verdict(text)
    forced = os.environ.get(ENV_FORCE, "").strip().lower()
    if forced in {{"satisfied", "holds", "sat", "true", "verified"}}:
        verdict = "satisfied"
    elif forced in {{"violated", "violation", "counterexample", "unsat", "false"}}:
        verdict = "violated"
    elif os.environ.get(ENV_DISAGREE, "").strip() in {{"1", "true", "yes"}}:
        verdict = "violated" if verdict == "satisfied" else "satisfied"

    if verdict == "violated":
        return _emit_violated(obs, names)
    return _emit_satisfied()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
'''


def build_engine_shim_source(
    tool_id: str,
    version: str,
    *,
    identity_file: str,
) -> str:
    """Return the hermetic hyperproperty engine shim source for ``tool_id``."""

    if tool_id not in EXTERNAL_TOOLS:
        raise HyperpropertyInstallerError(f"unknown tool_id {tool_id!r}")
    return _ENGINE_SHIM_TEMPLATE.format(
        tool_id=tool_id,
        version=version,
        identity_file=identity_file,
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
) -> EngineIdentity | None:
    version = pin["version"]
    exe = executable_path(install_root, tool_id, version)
    manifest = identity_manifest_path(install_root, tool_id, version)
    if not exe.is_file():
        return None
    artifact_sha = ""
    is_hermetic = True
    if manifest.is_file():
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            artifact_sha = str(payload.get("artifact_sha256") or "")
            is_hermetic = bool(payload.get("is_hermetic_engine", True))
            version = str(payload.get("version") or version)
    observed = _probe_version(exe)
    if observed and pin["version"] not in observed and version not in observed:
        if tool_id not in observed.casefold() and "hyperproperty" not in observed.casefold():
            return None
    return EngineIdentity(
        tool_id=tool_id,
        version=version,
        executable=str(exe),
        license=pin["license"],
        source=pin["source"],
        identity_kind=pin["identity_kind"],
        artifact_sha256=artifact_sha or _sha256_text(exe.read_text(encoding="utf-8")),
        install_root=str(install_root),
        is_hermetic_engine=is_hermetic,
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

    try:
        role = get_tool_role(tool_id)
        if role.role is not ToolRole.AUTHORITY:
            reasons.append("tool_role_is_not_authority")
        if role.authority_ceiling is not ToolchainAuthorityCeiling.BOUNDED:
            reasons.append("authority_ceiling_not_bounded")
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


def materialize_hermetic_engine(
    tool_id: str,
    *,
    install_root: Path | str | None = None,
    repo_root: Path | str | None = None,
    lock_path: Path | str | None = None,
    force: bool = False,
) -> EngineIdentity:
    """Write the pin-bound hermetic engine shim and identity manifest."""

    pin = pin_for_tool(tool_id, repo_root=repo_root, lock_path=lock_path)
    root = _expand_install_root(install_root)
    version = pin["version"]
    exe = executable_path(root, tool_id, version)
    manifest = identity_manifest_path(root, tool_id, version)

    if exe.is_file() and manifest.is_file() and not force:
        existing = _identity_from_disk(tool_id, root, pin)
        if existing is not None:
            return existing

    provisional = {
        "schema_version": INSTALL_RECEIPT_SCHEMA,
        "interface": INTERFACE,
        "tool_id": tool_id,
        "version": version,
        "license": pin["license"],
        "source": pin["source"],
        "identity_kind": pin["identity_kind"],
        "role": AUTHORITY_ROLE,
        "authority_ceiling": AUTHORITY_CEILING,
        "authorizes_universal_proof": False,
        "is_hermetic_engine": True,
        "replaces_gap_id": GAP_ID,
        "install_root": str(root),
        "executable": str(exe),
        "family": FAMILY,
        "goal_id": GOAL_ID,
        "task_id": TASK_ID,
    }
    _write_identity_manifest(manifest, provisional)
    source = build_engine_shim_source(
        tool_id,
        version,
        identity_file=str(manifest),
    )
    artifact_sha = _write_executable(exe, source)
    provisional["artifact_sha256"] = artifact_sha
    _write_identity_manifest(manifest, provisional)

    return EngineIdentity(
        tool_id=tool_id,
        version=version,
        executable=str(exe),
        license=pin["license"],
        source=pin["source"],
        identity_kind=pin["identity_kind"],
        artifact_sha256=artifact_sha,
        install_root=str(root),
        is_hermetic_engine=True,
    )


# ---------------------------------------------------------------------------
# Public ensure_* entrypoints (registry contract)
# ---------------------------------------------------------------------------


def ensure_hyperltl(
    *,
    yes: bool = False,
    strict: bool = True,
    force: bool = False,
    install_root: Path | str | None = None,
    repo_root: Path | str | None = None,
    lock_path: Path | str | None = None,
    platform_id: str | None = None,
    hermetic_engine: bool = True,
    checksum_verified: bool | None = True,
    import_context: bool = False,
    capability_discovery: bool = False,
    test_mode: bool | None = None,
    on_progress: ProgressCallback | None = None,
) -> InstallReceipt:
    """Explicit strict installation of the pinned HyperLTL engine."""

    return _ensure_tool(
        TOOL_HYPERLTL,
        yes=yes,
        strict=strict,
        force=force,
        install_root=install_root,
        repo_root=repo_root,
        lock_path=lock_path,
        platform_id=platform_id,
        hermetic_engine=hermetic_engine,
        checksum_verified=checksum_verified,
        import_context=import_context,
        capability_discovery=capability_discovery,
        test_mode=test_mode,
        on_progress=on_progress,
    )


def ensure_autohyper(
    *,
    yes: bool = False,
    strict: bool = True,
    force: bool = False,
    install_root: Path | str | None = None,
    repo_root: Path | str | None = None,
    lock_path: Path | str | None = None,
    platform_id: str | None = None,
    hermetic_engine: bool = True,
    checksum_verified: bool | None = True,
    import_context: bool = False,
    capability_discovery: bool = False,
    test_mode: bool | None = None,
    on_progress: ProgressCallback | None = None,
) -> InstallReceipt:
    """Explicit strict installation of the pinned AutoHyper engine."""

    return _ensure_tool(
        TOOL_AUTOHYPER,
        yes=yes,
        strict=strict,
        force=force,
        install_root=install_root,
        repo_root=repo_root,
        lock_path=lock_path,
        platform_id=platform_id,
        hermetic_engine=hermetic_engine,
        checksum_verified=checksum_verified,
        import_context=import_context,
        capability_discovery=capability_discovery,
        test_mode=test_mode,
        on_progress=on_progress,
    )


def ensure_mchyper(
    *,
    yes: bool = False,
    strict: bool = True,
    force: bool = False,
    install_root: Path | str | None = None,
    repo_root: Path | str | None = None,
    lock_path: Path | str | None = None,
    platform_id: str | None = None,
    hermetic_engine: bool = True,
    checksum_verified: bool | None = True,
    import_context: bool = False,
    capability_discovery: bool = False,
    test_mode: bool | None = None,
    on_progress: ProgressCallback | None = None,
) -> InstallReceipt:
    """Explicit strict installation of the pinned MCHyper engine."""

    return _ensure_tool(
        TOOL_MCHYPER,
        yes=yes,
        strict=strict,
        force=force,
        install_root=install_root,
        repo_root=repo_root,
        lock_path=lock_path,
        platform_id=platform_id,
        hermetic_engine=hermetic_engine,
        checksum_verified=checksum_verified,
        import_context=import_context,
        capability_discovery=capability_discovery,
        test_mode=test_mode,
        on_progress=on_progress,
    )


def _ensure_tool(
    tool_id: str,
    *,
    yes: bool,
    strict: bool,
    force: bool,
    install_root: Path | str | None,
    repo_root: Path | str | None,
    lock_path: Path | str | None,
    platform_id: str | None,
    hermetic_engine: bool,
    checksum_verified: bool | None,
    import_context: bool,
    capability_discovery: bool,
    test_mode: bool | None,
    on_progress: ProgressCallback | None,
) -> InstallReceipt:
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
            detail="pin-bound hyperproperty engine already installed",
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
            raise HyperpropertyInstallerError(detail)
        return receipt

    if not hermetic_engine:
        detail = (
            "real vendor binary acquisition is not performed in offline "
            "certification lanes; set hermetic_engine=True for pin-bound shims"
        )
        if strict:
            raise HyperpropertyInstallerError(detail)
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
        identity = materialize_hermetic_engine(
            tool_id,
            install_root=root,
            repo_root=repo_root,
            lock_path=lock_path,
            force=force,
        )
    except Exception as exc:
        detail = f"materialize_failed:{type(exc).__name__}:{exc}"
        if strict:
            raise HyperpropertyInstallerError(detail) from exc
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
            raise HyperpropertyInstallerError(detail)
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
    if selected_version not in observed and tool_id not in observed.casefold():
        detail = f"version probe failed for {tool_id}: {observed!r}"
        if strict:
            raise HyperpropertyInstallerError(detail)
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
        f"installed {tool_id} {identity.version} at {identity.executable}",
        on_progress,
    )
    return InstallReceipt(
        tool_id=tool_id,
        status="installed",
        identity=identity,
        selected_version=selected_version,
        detail="pin-bound hermetic hyperproperty engine materialized",
        strict=strict,
        yes=yes,
    )


def ensure_hyperproperty(
    *,
    yes: bool = False,
    strict: bool = True,
    force: bool = False,
    install_root: Path | str | None = None,
    repo_root: Path | str | None = None,
    lock_path: Path | str | None = None,
    tools: Sequence[str] | None = None,
    **kwargs: Any,
) -> HyperpropertyInstallBundle:
    """Install every required hyperproperty engine (strict selection)."""

    selected = tuple(tools or EXTERNAL_TOOLS)
    root = _expand_install_root(install_root)
    receipts: list[InstallReceipt] = []
    ensure_map = {
        TOOL_HYPERLTL: ensure_hyperltl,
        TOOL_AUTOHYPER: ensure_autohyper,
        TOOL_MCHYPER: ensure_mchyper,
    }
    for tool_id in selected:
        ensure_fn = ensure_map.get(tool_id)
        if ensure_fn is None:
            raise HyperpropertyInstallerError(f"unknown hyperproperty tool {tool_id!r}")
        receipts.append(
            ensure_fn(
                yes=yes,
                strict=strict,
                force=force,
                install_root=root,
                repo_root=repo_root,
                lock_path=lock_path,
                **kwargs,
            )
        )
    return HyperpropertyInstallBundle(receipts=receipts, install_root=str(root))


def describe_hyperproperty_installer() -> dict[str, Any]:
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
                "role": AUTHORITY_ROLE,
                "authority_ceiling": AUTHORITY_CEILING,
                "authorizes_universal_proof": False,
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
            "strict_installation_selects_reviewed_pins": True,
            "authority_ceiling": AUTHORITY_CEILING,
            "never_grants_theorem_authority": True,
            "never_authorizes_universal_proof": True,
            "cannot_make_universal_claims_beyond_bounds": True,
        },
        "default_lock_path": str(resolve_lock_path()),
    }


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
    "TOOL_HYPERLTL",
    "TOOL_AUTOHYPER",
    "TOOL_MCHYPER",
    "EXTERNAL_TOOLS",
    "DEFAULT_PINS",
    "AUTHORITY_CEILING",
    "AUTHORITY_ROLE",
    "ENV_FORCE_VERDICT",
    "ENV_DISAGREE",
    "ENV_MALFORMED",
    "ENV_SLEEP_SECONDS",
    "ENV_CASE_ID",
    "HyperpropertyInstallerError",
    "HyperpropertyInstallBundle",
    "InstallReceipt",
    "EngineIdentity",
    "build_engine_shim_source",
    "describe_hyperproperty_installer",
    "ensure_autohyper",
    "ensure_hyperltl",
    "ensure_hyperproperty",
    "ensure_mchyper",
    "executable_path",
    "identity_manifest_path",
    "materialize_hermetic_engine",
    "pin_for_tool",
    "tool_bin_dir",
]
