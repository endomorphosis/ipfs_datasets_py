"""LogicPlatformManifest@1 — package-neutral handshake surface (LPC-100).

Exposes package identity, interface versions, catalog root, schema roots,
operation versions, receipt/plan versions, compatible adapter versions, and
optional source commit for supervisor handshake.

Design invariants
-----------------
* Works from installed wheels: no sibling-repo layout, no Git working tree,
  and no repository-root discovery is required for a successful handshake.
* Git / VCS commit is **optional provenance only**.  Absence never fails the
  default handshake; callers that demand a commit get a typed incompatibility.
* Semantic compatibility is decided from declared interface and version maps,
  never from local checkout adjacency or Git metadata.
* Importing this module is side-effect free: no network, install, probe, or
  filesystem mutation.
"""

from __future__ import annotations

import importlib.metadata
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.backends.provider import (
    LOGIC_PROVIDER_PROTOCOL_VERSION,
    LOGIC_PROVIDER_REQUEST_SCHEMA,
    LOGIC_PROVIDER_RESPONSE_SCHEMA,
)
from ipfs_datasets_py.logic.backends.requests_v2 import (
    BACKEND_REQUEST_V2_INTERFACE,
    BACKEND_REQUEST_V2_SCHEMA_VERSION,
    LOGIC_OBLIGATION_V2_INTERFACE,
    LOGIC_OBLIGATION_V2_SCHEMA_VERSION,
)
from ipfs_datasets_py.logic.families.canonical_catalog import (
    CANONICAL_CATALOG_SNAPSHOT_INTERFACE,
    CANONICAL_CATALOG_SNAPSHOT_SCHEMA,
    CANONICAL_CATALOG_SNAPSHOT_VERSION,
    DEFAULT_CANONICAL_CATALOG_SNAPSHOT,
)

# Declared interface/schema ids for peer contracts. Kept as local constants so
# the handshake surface stays a thin import graph (no formalization/tactician
# package load required for identity advertisement).
FORMALIZATION_ARTIFACT_V3_INTERFACE: Final = "FormalizationArtifact@3"
DOMAIN_LOGIC_SLICE_V2_INTERFACE: Final = "DomainLogicSlice@2"
FORMALIZATION_ARTIFACT_V3_SCHEMA_VERSION: Final = "formalization-artifact/v3"
DOMAIN_LOGIC_SLICE_V2_SCHEMA_VERSION: Final = "domain-logic-slice/v2"
GOAL_DIRECTED_PROOF_PLAN_INTERFACE: Final = "GoalDirectedProofPlan@1"
GOAL_DIRECTED_PROOF_PLAN_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/goal-directed-proof-plan@1"
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

LOGIC_PLATFORM_MANIFEST_INTERFACE: Final = "LogicPlatformManifest@1"
LOGIC_PLATFORM_MANIFEST_SCHEMA: Final = "logic-platform-manifest/v1"
LOGIC_PLATFORM_MANIFEST_VERSION: Final = "1.0.0"
LOGIC_PLATFORM_MANIFEST_TASK_ID: Final = "LPC-100"
LOGIC_PLATFORM_MANIFEST_GOAL_ID: Final = "LPC-G100"
HANDSHAKE_RESULT_SCHEMA: Final = "logic-platform-handshake-result/v1"

PACKAGE_NAME: Final = "ipfs_datasets_py"
PACKAGE_DISTRIBUTION_NAMES: Final = (
    "ipfs_datasets_py",
    "ipfs-datasets-py",
    "ipfs-datasets",
)

# Supervisor-facing adapter contracts this platform claims compatibility with.
DEFAULT_COMPATIBLE_ADAPTER_VERSIONS: Final[tuple[str, ...]] = (
    "SupervisorCanonicalLogicAdapter@1",
    "SupervisorLogicPlatformClient@1",
)

# Optional provenance env keys (never required for handshake success).
_SOURCE_COMMIT_ENV_KEYS: Final[tuple[str, ...]] = (
    "LOGIC_PLATFORM_SOURCE_COMMIT",
    "IPFS_DATASETS_SOURCE_COMMIT",
    "IPFS_DATASETS_PY_SOURCE_COMMIT",
)

_SEMVER_FRAGMENT_RE = re.compile(r"(\d+)")


class LogicPlatformManifestError(ValueError):
    """Raised when a manifest or handshake request is structurally invalid."""


class IncompatibilityCode(str, Enum):
    """Closed vocabulary for typed handshake incompatibilities."""

    MANIFEST_INTERFACE = "manifest_interface"
    PACKAGE_NAME = "package_name"
    PACKAGE_VERSION = "package_version"
    INTERFACE_VERSION = "interface_version"
    CATALOG_ROOT = "catalog_root"
    CATALOG_DIGEST = "catalog_digest"
    SCHEMA_ROOT = "schema_root"
    OPERATION_VERSION = "operation_version"
    RECEIPT_VERSION = "receipt_version"
    PLAN_VERSION = "plan_version"
    ADAPTER_VERSION = "adapter_version"
    SOURCE_COMMIT_REQUIRED = "source_commit_required"
    SOURCE_COMMIT_MISMATCH = "source_commit_mismatch"


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise LogicPlatformManifestError(
            f"{field_name} must be a non-empty trimmed string"
        )
    if "\x00" in value:
        raise LogicPlatformManifestError(
            f"{field_name} must not contain NUL bytes"
        )
    return value


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise LogicPlatformManifestError(
            f"{field_name} must be a string or None"
        )
    stripped = value.strip()
    if not stripped:
        return None
    if "\x00" in stripped:
        raise LogicPlatformManifestError(
            f"{field_name} must not contain NUL bytes"
        )
    return stripped


def _freeze_str_map(
    value: Mapping[str, str] | None,
    *,
    field_name: str,
) -> Mapping[str, str]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise LogicPlatformManifestError(f"{field_name} must be a mapping")
    frozen: dict[str, str] = {}
    for raw_key, raw_item in value.items():
        key = _text(raw_key, f"{field_name} key")
        item = _text(raw_item, f"{field_name}[{key!r}]")
        if key in frozen:
            raise LogicPlatformManifestError(
                f"{field_name} contains duplicate key {key!r}"
            )
        frozen[key] = item
    return MappingProxyType(dict(sorted(frozen.items())))


def _freeze_str_tuple(
    value: Sequence[str] | None,
    *,
    field_name: str,
) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise LogicPlatformManifestError(f"{field_name} must be a sequence")
    items: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(value):
        item = _text(raw, f"{field_name}[{index}]")
        if item in seen:
            raise LogicPlatformManifestError(
                f"{field_name} contains duplicate entry {item!r}"
            )
        seen.add(item)
        items.append(item)
    return tuple(items)


def _version_key(version: str) -> tuple[int, ...]:
    """Best-effort numeric key for package/interface version comparison."""

    parts = [int(match.group(1)) for match in _SEMVER_FRAGMENT_RE.finditer(version)]
    return tuple(parts) if parts else (0,)


def resolve_package_version(
    package_name: str = PACKAGE_NAME,
    *,
    fallback: str | None = None,
) -> str:
    """Resolve an installed distribution version without Git or siblings.

    Order:
    1. ``importlib.metadata`` for known distribution names
    2. ``ipfs_datasets_py.__version__`` when the package is importable
    3. explicit *fallback*
    4. hard default ``0.0.0`` (still a valid handshake identity)
    """

    names = (package_name, *PACKAGE_DISTRIBUTION_NAMES)
    seen: set[str] = set()
    for name in names:
        key = str(name or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        try:
            return importlib.metadata.version(key)
        except importlib.metadata.PackageNotFoundError:
            continue
        except Exception:
            continue

    try:
        import ipfs_datasets_py as _pkg

        version = getattr(_pkg, "__version__", None)
        if isinstance(version, str) and version.strip():
            return version.strip()
    except Exception:
        pass

    if fallback is not None and str(fallback).strip():
        return str(fallback).strip()
    return "0.0.0"


def optional_source_commit(
    *,
    explicit: str | None = None,
    environ: Mapping[str, str] | None = None,
    package_name: str = PACKAGE_NAME,
) -> str | None:
    """Return optional VCS provenance without consulting Git or siblings.

    Sources (first hit wins):

    * explicit caller value
    * environment keys in :data:`_SOURCE_COMMIT_ENV_KEYS`
    * package metadata ``Source-Commit`` / ``Git-Commit`` / ``Vcs-Commit``

    Missing provenance returns ``None``.  This function never walks the
    filesystem for ``.git``, never shells out to ``git``, and never inspects
    sibling repositories.
    """

    if explicit is not None:
        return _optional_text(explicit, "source_commit")

    env = os.environ if environ is None else environ
    for key in _SOURCE_COMMIT_ENV_KEYS:
        raw = env.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()

    names = (package_name, *PACKAGE_DISTRIBUTION_NAMES)
    seen: set[str] = set()
    for name in names:
        key = str(name or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        try:
            meta = importlib.metadata.metadata(key)
        except importlib.metadata.PackageNotFoundError:
            continue
        except Exception:
            continue
        for field_name in ("Source-Commit", "Git-Commit", "Vcs-Commit"):
            value = meta.get(field_name) if meta is not None else None
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _default_interface_versions() -> Mapping[str, str]:
    return MappingProxyType(
        {
            LOGIC_PLATFORM_MANIFEST_INTERFACE: LOGIC_PLATFORM_MANIFEST_VERSION,
            CANONICAL_CATALOG_SNAPSHOT_INTERFACE: CANONICAL_CATALOG_SNAPSHOT_VERSION,
            FORMALIZATION_ARTIFACT_V3_INTERFACE: "3",
            DOMAIN_LOGIC_SLICE_V2_INTERFACE: "2",
            LOGIC_OBLIGATION_V2_INTERFACE: "2",
            BACKEND_REQUEST_V2_INTERFACE: "2",
            GOAL_DIRECTED_PROOF_PLAN_INTERFACE: "1",
            "LogicProviderProtocol@1": str(LOGIC_PROVIDER_PROTOCOL_VERSION),
        }
    )


def _default_schema_roots() -> Mapping[str, str]:
    return MappingProxyType(
        {
            "catalog_snapshot": CANONICAL_CATALOG_SNAPSHOT_SCHEMA,
            "formalization_artifact": FORMALIZATION_ARTIFACT_V3_SCHEMA_VERSION,
            "domain_logic_slice": DOMAIN_LOGIC_SLICE_V2_SCHEMA_VERSION,
            "logic_obligation": LOGIC_OBLIGATION_V2_SCHEMA_VERSION,
            "backend_request": BACKEND_REQUEST_V2_SCHEMA_VERSION,
            "goal_directed_proof_plan": GOAL_DIRECTED_PROOF_PLAN_SCHEMA,
            "provider_request": LOGIC_PROVIDER_REQUEST_SCHEMA,
            "provider_response": LOGIC_PROVIDER_RESPONSE_SCHEMA,
            "manifest": LOGIC_PLATFORM_MANIFEST_SCHEMA,
        }
    )


def _default_operation_versions() -> Mapping[str, str]:
    protocol = str(LOGIC_PROVIDER_PROTOCOL_VERSION)
    return MappingProxyType(
        {
            "capability": protocol,
            "translate": protocol,
            "prove": protocol,
            "reconstruct": protocol,
            "verify": protocol,
            "attest": protocol,
            "handshake": LOGIC_PLATFORM_MANIFEST_VERSION,
            "catalog": CANONICAL_CATALOG_SNAPSHOT_VERSION,
        }
    )


def _default_receipt_versions() -> Mapping[str, str]:
    return MappingProxyType(
        {
            "logic_translation_receipt": "logic-translation-receipt/v1",
            "trusted_proof_receipt": "trusted-proof-receipt/v1",
            "handshake_result": HANDSHAKE_RESULT_SCHEMA,
        }
    )


def _default_plan_versions() -> Mapping[str, str]:
    return MappingProxyType(
        {
            "goal_directed_proof_plan": GOAL_DIRECTED_PROOF_PLAN_SCHEMA,
            "formal_work_plan": "ipfs_accelerate_py/agent-supervisor/formal-work-plan@1",
        }
    )


@dataclass(frozen=True, slots=True)
class LogicPlatformManifest:
    """Package-neutral logic platform identity for supervisor handshake.

    Interface: ``LogicPlatformManifest@1``.
    """

    package_name: str
    package_version: str
    interface_versions: Mapping[str, str]
    catalog_root: str
    catalog_digest: str
    schema_roots: Mapping[str, str]
    operation_versions: Mapping[str, str]
    receipt_versions: Mapping[str, str]
    plan_versions: Mapping[str, str]
    compatible_adapter_versions: tuple[str, ...]
    source_commit: str | None = None
    version: str = LOGIC_PLATFORM_MANIFEST_VERSION
    schema_version: str = LOGIC_PLATFORM_MANIFEST_SCHEMA
    task_id: str = LOGIC_PLATFORM_MANIFEST_TASK_ID
    goal_id: str = LOGIC_PLATFORM_MANIFEST_GOAL_ID
    notes: str = (
        "Package-neutral handshake surface. Works from wheels without sibling "
        "repos or Git metadata. Source commit is optional provenance only."
    )

    INTERFACE: ClassVar[str] = LOGIC_PLATFORM_MANIFEST_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "package_name", _text(self.package_name, "package_name")
        )
        object.__setattr__(
            self,
            "package_version",
            _text(self.package_version, "package_version"),
        )
        object.__setattr__(
            self,
            "interface_versions",
            _freeze_str_map(
                dict(self.interface_versions),
                field_name="interface_versions",
            ),
        )
        object.__setattr__(
            self, "catalog_root", _text(self.catalog_root, "catalog_root")
        )
        object.__setattr__(
            self,
            "catalog_digest",
            _text(self.catalog_digest, "catalog_digest"),
        )
        if not self.catalog_digest.startswith("sha256:"):
            raise LogicPlatformManifestError(
                "catalog_digest must be a sha256: digest"
            )
        object.__setattr__(
            self,
            "schema_roots",
            _freeze_str_map(dict(self.schema_roots), field_name="schema_roots"),
        )
        object.__setattr__(
            self,
            "operation_versions",
            _freeze_str_map(
                dict(self.operation_versions),
                field_name="operation_versions",
            ),
        )
        object.__setattr__(
            self,
            "receipt_versions",
            _freeze_str_map(
                dict(self.receipt_versions),
                field_name="receipt_versions",
            ),
        )
        object.__setattr__(
            self,
            "plan_versions",
            _freeze_str_map(dict(self.plan_versions), field_name="plan_versions"),
        )
        object.__setattr__(
            self,
            "compatible_adapter_versions",
            _freeze_str_tuple(
                self.compatible_adapter_versions,
                field_name="compatible_adapter_versions",
            ),
        )
        object.__setattr__(
            self,
            "source_commit",
            _optional_text(self.source_commit, "source_commit"),
        )
        object.__setattr__(self, "version", _text(self.version, "version"))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != LOGIC_PLATFORM_MANIFEST_SCHEMA:
            raise LogicPlatformManifestError(
                f"unsupported manifest schema {self.schema_version!r}"
            )
        object.__setattr__(self, "task_id", _text(self.task_id, "task_id"))
        object.__setattr__(self, "goal_id", _text(self.goal_id, "goal_id"))
        object.__setattr__(
            self, "notes", _text(self.notes, "notes") if self.notes else ""
        )
        if LOGIC_PLATFORM_MANIFEST_INTERFACE not in self.interface_versions:
            raise LogicPlatformManifestError(
                "interface_versions must declare LogicPlatformManifest@1"
            )

    @property
    def interface(self) -> str:
        return self.INTERFACE

    @property
    def git_provenance_available(self) -> bool:
        """True only when optional source commit provenance is present."""

        return self.source_commit is not None

    def requires_git(self) -> bool:
        """Manifest construction and handshake never require Git."""

        return False

    def requires_sibling_repos(self) -> bool:
        """Manifest construction never requires sibling repository checkouts."""

        return False

    def requires_repository_layout(self) -> bool:
        """Local repository layout is never semantic compatibility authority."""

        return False

    def to_dict(self) -> dict[str, Any]:
        """JSON-compatible envelope with stable key ordering."""

        return {
            "catalog_digest": self.catalog_digest,
            "catalog_root": self.catalog_root,
            "compatible_adapter_versions": list(self.compatible_adapter_versions),
            "git_provenance_available": self.git_provenance_available,
            "goal_id": self.goal_id,
            "interface": self.interface,
            "interface_versions": dict(self.interface_versions),
            "notes": self.notes,
            "operation_versions": dict(self.operation_versions),
            "package_name": self.package_name,
            "package_version": self.package_version,
            "plan_versions": dict(self.plan_versions),
            "receipt_versions": dict(self.receipt_versions),
            "requires_git": self.requires_git(),
            "requires_repository_layout": self.requires_repository_layout(),
            "requires_sibling_repos": self.requires_sibling_repos(),
            "schema_roots": dict(self.schema_roots),
            "schema_version": self.schema_version,
            "source_commit": self.source_commit,
            "task_id": self.task_id,
            "version": self.version,
        }


@dataclass(frozen=True, slots=True)
class HandshakeRequirements:
    """Caller-declared compatibility requirements for a platform handshake."""

    required_manifest_interface: str = LOGIC_PLATFORM_MANIFEST_INTERFACE
    required_package_name: str | None = PACKAGE_NAME
    min_package_version: str | None = None
    exact_package_version: str | None = None
    required_interface_versions: Mapping[str, str] = field(default_factory=dict)
    required_schema_roots: Mapping[str, str] = field(default_factory=dict)
    required_operation_versions: Mapping[str, str] = field(default_factory=dict)
    required_receipt_versions: Mapping[str, str] = field(default_factory=dict)
    required_plan_versions: Mapping[str, str] = field(default_factory=dict)
    required_adapter_versions: tuple[str, ...] = ()
    required_catalog_root: str | None = None
    required_catalog_digest: str | None = None
    required_source_commit: str | None = None
    require_source_commit: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "required_manifest_interface",
            _text(
                self.required_manifest_interface,
                "required_manifest_interface",
            ),
        )
        object.__setattr__(
            self,
            "required_package_name",
            _optional_text(self.required_package_name, "required_package_name"),
        )
        object.__setattr__(
            self,
            "min_package_version",
            _optional_text(self.min_package_version, "min_package_version"),
        )
        object.__setattr__(
            self,
            "exact_package_version",
            _optional_text(self.exact_package_version, "exact_package_version"),
        )
        object.__setattr__(
            self,
            "required_interface_versions",
            _freeze_str_map(
                dict(self.required_interface_versions),
                field_name="required_interface_versions",
            ),
        )
        object.__setattr__(
            self,
            "required_schema_roots",
            _freeze_str_map(
                dict(self.required_schema_roots),
                field_name="required_schema_roots",
            ),
        )
        object.__setattr__(
            self,
            "required_operation_versions",
            _freeze_str_map(
                dict(self.required_operation_versions),
                field_name="required_operation_versions",
            ),
        )
        object.__setattr__(
            self,
            "required_receipt_versions",
            _freeze_str_map(
                dict(self.required_receipt_versions),
                field_name="required_receipt_versions",
            ),
        )
        object.__setattr__(
            self,
            "required_plan_versions",
            _freeze_str_map(
                dict(self.required_plan_versions),
                field_name="required_plan_versions",
            ),
        )
        object.__setattr__(
            self,
            "required_adapter_versions",
            _freeze_str_tuple(
                self.required_adapter_versions,
                field_name="required_adapter_versions",
            ),
        )
        object.__setattr__(
            self,
            "required_catalog_root",
            _optional_text(self.required_catalog_root, "required_catalog_root"),
        )
        object.__setattr__(
            self,
            "required_catalog_digest",
            _optional_text(
                self.required_catalog_digest, "required_catalog_digest"
            ),
        )
        object.__setattr__(
            self,
            "required_source_commit",
            _optional_text(
                self.required_source_commit, "required_source_commit"
            ),
        )
        if not isinstance(self.require_source_commit, bool):
            raise LogicPlatformManifestError(
                "require_source_commit must be a bool"
            )


@dataclass(frozen=True, slots=True)
class ManifestIncompatibility:
    """One typed incompatibility discovered during handshake."""

    code: IncompatibilityCode
    field: str
    expected: str
    actual: str
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.code, IncompatibilityCode):
            object.__setattr__(
                self, "code", IncompatibilityCode(str(self.code))
            )
        object.__setattr__(self, "field", _text(self.field, "field"))
        object.__setattr__(
            self, "expected", str(self.expected) if self.expected is not None else ""
        )
        object.__setattr__(
            self, "actual", str(self.actual) if self.actual is not None else ""
        )
        object.__setattr__(self, "message", _text(self.message, "message"))

    def to_dict(self) -> dict[str, str]:
        return {
            "actual": self.actual,
            "code": self.code.value,
            "expected": self.expected,
            "field": self.field,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class HandshakeResult:
    """Typed outcome of a LogicPlatformManifest@1 handshake."""

    compatible: bool
    manifest: LogicPlatformManifest
    incompatibilities: tuple[ManifestIncompatibility, ...] = ()
    schema_version: str = HANDSHAKE_RESULT_SCHEMA

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, LogicPlatformManifest):
            raise LogicPlatformManifestError(
                "manifest must be a LogicPlatformManifest"
            )
        if not isinstance(self.compatible, bool):
            raise LogicPlatformManifestError("compatible must be a bool")
        object.__setattr__(
            self,
            "incompatibilities",
            tuple(self.incompatibilities or ()),
        )
        for item in self.incompatibilities:
            if not isinstance(item, ManifestIncompatibility):
                raise LogicPlatformManifestError(
                    "incompatibilities must contain ManifestIncompatibility"
                )
        if self.compatible and self.incompatibilities:
            raise LogicPlatformManifestError(
                "compatible handshake cannot carry incompatibilities"
            )
        if not self.compatible and not self.incompatibilities:
            raise LogicPlatformManifestError(
                "incompatible handshake must carry at least one incompatibility"
            )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != HANDSHAKE_RESULT_SCHEMA:
            raise LogicPlatformManifestError(
                f"unsupported handshake schema {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "compatible": self.compatible,
            "incompatibilities": [
                item.to_dict() for item in self.incompatibilities
            ],
            "manifest": self.manifest.to_dict(),
            "schema_version": self.schema_version,
        }


def build_logic_platform_manifest(
    *,
    package_name: str = PACKAGE_NAME,
    package_version: str | None = None,
    catalog_root: str | None = None,
    catalog_digest: str | None = None,
    interface_versions: Mapping[str, str] | None = None,
    schema_roots: Mapping[str, str] | None = None,
    operation_versions: Mapping[str, str] | None = None,
    receipt_versions: Mapping[str, str] | None = None,
    plan_versions: Mapping[str, str] | None = None,
    compatible_adapter_versions: Sequence[str] | None = None,
    source_commit: str | None = None,
    include_source_commit: bool = True,
    environ: Mapping[str, str] | None = None,
) -> LogicPlatformManifest:
    """Build a package-neutral manifest from installed package state.

    Does not require Git metadata, a repository checkout, or sibling repos.
    """

    snapshot = DEFAULT_CANONICAL_CATALOG_SNAPSHOT
    resolved_version = (
        _text(package_version, "package_version")
        if package_version is not None
        else resolve_package_version(package_name)
    )
    resolved_commit: str | None = None
    if include_source_commit:
        resolved_commit = optional_source_commit(
            explicit=source_commit,
            environ=environ,
            package_name=package_name,
        )
    elif source_commit is not None:
        resolved_commit = _optional_text(source_commit, "source_commit")

    return LogicPlatformManifest(
        package_name=package_name,
        package_version=resolved_version,
        interface_versions=(
            dict(interface_versions)
            if interface_versions is not None
            else dict(_default_interface_versions())
        ),
        catalog_root=(
            catalog_root if catalog_root is not None else snapshot.content_root
        ),
        catalog_digest=(
            catalog_digest
            if catalog_digest is not None
            else snapshot.content_digest
        ),
        schema_roots=(
            dict(schema_roots)
            if schema_roots is not None
            else dict(_default_schema_roots())
        ),
        operation_versions=(
            dict(operation_versions)
            if operation_versions is not None
            else dict(_default_operation_versions())
        ),
        receipt_versions=(
            dict(receipt_versions)
            if receipt_versions is not None
            else dict(_default_receipt_versions())
        ),
        plan_versions=(
            dict(plan_versions)
            if plan_versions is not None
            else dict(_default_plan_versions())
        ),
        compatible_adapter_versions=(
            tuple(compatible_adapter_versions)
            if compatible_adapter_versions is not None
            else DEFAULT_COMPATIBLE_ADAPTER_VERSIONS
        ),
        source_commit=resolved_commit,
    )


def _map_mismatches(
    *,
    required: Mapping[str, str],
    actual: Mapping[str, str],
    code: IncompatibilityCode,
    field_prefix: str,
) -> list[ManifestIncompatibility]:
    findings: list[ManifestIncompatibility] = []
    for key, expected in required.items():
        have = actual.get(key)
        if have is None:
            findings.append(
                ManifestIncompatibility(
                    code=code,
                    field=f"{field_prefix}.{key}",
                    expected=expected,
                    actual="",
                    message=f"missing {field_prefix} entry {key!r}",
                )
            )
        elif have != expected:
            findings.append(
                ManifestIncompatibility(
                    code=code,
                    field=f"{field_prefix}.{key}",
                    expected=expected,
                    actual=have,
                    message=(
                        f"{field_prefix} {key!r} is {have!r}, "
                        f"required {expected!r}"
                    ),
                )
            )
    return findings


def handshake(
    requirements: HandshakeRequirements | Mapping[str, Any] | None = None,
    *,
    manifest: LogicPlatformManifest | None = None,
) -> HandshakeResult:
    """Perform a package-neutral compatibility handshake.

    Returns a typed :class:`HandshakeResult`.  Version mismatches never raise;
    only structurally invalid inputs raise :class:`LogicPlatformManifestError`.
    """

    if requirements is None:
        req = HandshakeRequirements()
    elif isinstance(requirements, HandshakeRequirements):
        req = requirements
    elif isinstance(requirements, Mapping):
        req = HandshakeRequirements(**dict(requirements))
    else:
        raise LogicPlatformManifestError(
            "requirements must be HandshakeRequirements, a mapping, or None"
        )

    platform = (
        manifest if manifest is not None else build_logic_platform_manifest()
    )
    if not isinstance(platform, LogicPlatformManifest):
        raise LogicPlatformManifestError(
            "manifest must be a LogicPlatformManifest"
        )

    findings: list[ManifestIncompatibility] = []

    if platform.interface != req.required_manifest_interface:
        findings.append(
            ManifestIncompatibility(
                code=IncompatibilityCode.MANIFEST_INTERFACE,
                field="interface",
                expected=req.required_manifest_interface,
                actual=platform.interface,
                message=(
                    f"manifest interface is {platform.interface!r}, "
                    f"required {req.required_manifest_interface!r}"
                ),
            )
        )

    if (
        req.required_package_name is not None
        and platform.package_name != req.required_package_name
    ):
        findings.append(
            ManifestIncompatibility(
                code=IncompatibilityCode.PACKAGE_NAME,
                field="package_name",
                expected=req.required_package_name,
                actual=platform.package_name,
                message=(
                    f"package_name is {platform.package_name!r}, "
                    f"required {req.required_package_name!r}"
                ),
            )
        )

    if req.exact_package_version is not None and (
        platform.package_version != req.exact_package_version
    ):
        findings.append(
            ManifestIncompatibility(
                code=IncompatibilityCode.PACKAGE_VERSION,
                field="package_version",
                expected=req.exact_package_version,
                actual=platform.package_version,
                message=(
                    f"package_version is {platform.package_version!r}, "
                    f"required exact {req.exact_package_version!r}"
                ),
            )
        )
    elif req.min_package_version is not None:
        if _version_key(platform.package_version) < _version_key(
            req.min_package_version
        ):
            findings.append(
                ManifestIncompatibility(
                    code=IncompatibilityCode.PACKAGE_VERSION,
                    field="package_version",
                    expected=f">={req.min_package_version}",
                    actual=platform.package_version,
                    message=(
                        f"package_version {platform.package_version!r} is "
                        f"below minimum {req.min_package_version!r}"
                    ),
                )
            )

    findings.extend(
        _map_mismatches(
            required=req.required_interface_versions,
            actual=platform.interface_versions,
            code=IncompatibilityCode.INTERFACE_VERSION,
            field_prefix="interface_versions",
        )
    )
    findings.extend(
        _map_mismatches(
            required=req.required_schema_roots,
            actual=platform.schema_roots,
            code=IncompatibilityCode.SCHEMA_ROOT,
            field_prefix="schema_roots",
        )
    )
    findings.extend(
        _map_mismatches(
            required=req.required_operation_versions,
            actual=platform.operation_versions,
            code=IncompatibilityCode.OPERATION_VERSION,
            field_prefix="operation_versions",
        )
    )
    findings.extend(
        _map_mismatches(
            required=req.required_receipt_versions,
            actual=platform.receipt_versions,
            code=IncompatibilityCode.RECEIPT_VERSION,
            field_prefix="receipt_versions",
        )
    )
    findings.extend(
        _map_mismatches(
            required=req.required_plan_versions,
            actual=platform.plan_versions,
            code=IncompatibilityCode.PLAN_VERSION,
            field_prefix="plan_versions",
        )
    )

    if req.required_catalog_root is not None and (
        platform.catalog_root != req.required_catalog_root
    ):
        findings.append(
            ManifestIncompatibility(
                code=IncompatibilityCode.CATALOG_ROOT,
                field="catalog_root",
                expected=req.required_catalog_root,
                actual=platform.catalog_root,
                message="catalog_root does not match required content root",
            )
        )

    if req.required_catalog_digest is not None and (
        platform.catalog_digest != req.required_catalog_digest
    ):
        findings.append(
            ManifestIncompatibility(
                code=IncompatibilityCode.CATALOG_DIGEST,
                field="catalog_digest",
                expected=req.required_catalog_digest,
                actual=platform.catalog_digest,
                message="catalog_digest does not match required content digest",
            )
        )

    compatible_adapters = set(platform.compatible_adapter_versions)
    for adapter in req.required_adapter_versions:
        if adapter not in compatible_adapters:
            findings.append(
                ManifestIncompatibility(
                    code=IncompatibilityCode.ADAPTER_VERSION,
                    field="compatible_adapter_versions",
                    expected=adapter,
                    actual=",".join(platform.compatible_adapter_versions),
                    message=f"adapter {adapter!r} is not listed as compatible",
                )
            )

    if req.require_source_commit and platform.source_commit is None:
        findings.append(
            ManifestIncompatibility(
                code=IncompatibilityCode.SOURCE_COMMIT_REQUIRED,
                field="source_commit",
                expected="non-empty source commit",
                actual="",
                message=(
                    "caller required source_commit provenance, but the "
                    "installed package exposes none (Git is optional)"
                ),
            )
        )
    elif (
        req.required_source_commit is not None
        and platform.source_commit != req.required_source_commit
    ):
        findings.append(
            ManifestIncompatibility(
                code=IncompatibilityCode.SOURCE_COMMIT_MISMATCH,
                field="source_commit",
                expected=req.required_source_commit,
                actual=platform.source_commit or "",
                message="source_commit provenance does not match requirement",
            )
        )

    return HandshakeResult(
        compatible=not findings,
        manifest=platform,
        incompatibilities=tuple(findings),
    )


DEFAULT_LOGIC_PLATFORM_MANIFEST: Final[LogicPlatformManifest] = (
    build_logic_platform_manifest(include_source_commit=True)
)


__all__ = [
    "DEFAULT_COMPATIBLE_ADAPTER_VERSIONS",
    "DEFAULT_LOGIC_PLATFORM_MANIFEST",
    "HANDSHAKE_RESULT_SCHEMA",
    "LOGIC_PLATFORM_MANIFEST_GOAL_ID",
    "LOGIC_PLATFORM_MANIFEST_INTERFACE",
    "LOGIC_PLATFORM_MANIFEST_SCHEMA",
    "LOGIC_PLATFORM_MANIFEST_TASK_ID",
    "LOGIC_PLATFORM_MANIFEST_VERSION",
    "PACKAGE_NAME",
    "HandshakeRequirements",
    "HandshakeResult",
    "IncompatibilityCode",
    "LogicPlatformManifest",
    "LogicPlatformManifestError",
    "ManifestIncompatibility",
    "build_logic_platform_manifest",
    "handshake",
    "optional_source_commit",
    "resolve_package_version",
]
