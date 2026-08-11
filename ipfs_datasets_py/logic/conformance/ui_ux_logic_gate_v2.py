"""Exact-source-gated UI and accessibility logic adapter (LFP2-026).

Interfaces: ``UIUXLogicSlice@2``, ``UIUXSourceGate@2``

The pinned datasets tree does not invent, copy, or edit ``ui_ux_ir``.  When
the package is absent this module records a typed
``source_missing`` / ``declaration_only`` disposition and continues without
blocking other domain work.

When a reviewed exact source identity is present under the same scan, the
gate emits **exactly one** content-addressed, owner-scoped adapter gap whose
acceptance requires declared-syntax parsing, frame_logic alias
canonicalization, and typed structural round trips (not token presence).

``UIUXLogicSlice@2`` records the accessibility, interaction/event, workflow,
ontology/frame, authorization, and observable-state requirement surfaces that
the derived adapter must cover once source lands.

Side-effect policy: pure filesystem presence checks only. No network,
installation, model download, or subprocess at import or scan time.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.conformance.matrix import (
    AuthorityCeiling,
    AvailabilityStatus,
    SupportStatus,
)
from ipfs_datasets_py.logic.families.registry import (
    DEFAULT_REGISTRY,
    LogicFamilyRegistry,
    LogicFamilyRegistryError,
    UnknownDescriptorError,
)
from ipfs_datasets_py.logic.ir_core.claims import stable_digest


# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

UIUX_SOURCE_GATE_V2_INTERFACE: Final = "UIUXSourceGate@2"
UIUX_SOURCE_GATE_V2_VERSION: Final = "2.0.0"
UIUX_SOURCE_GATE_V2_SCHEMA: Final = "ui-ux-source-gate/v2"
UIUX_SOURCE_RECEIPT_V2_SCHEMA: Final = "ui-ux-source-gate-receipt/v2"
UIUX_SOURCE_IDENTITY_V2_SCHEMA: Final = "ui-ux-source-identity/v2"
UIUX_MATRIX_DISPOSITION_V2_SCHEMA: Final = "ui-ux-matrix-disposition/v2"
UIUX_ADAPTER_GAP_V2_SCHEMA: Final = "ui-ux-owner-scoped-adapter-gap/v2"

UIUX_LOGIC_SLICE_V2_INTERFACE: Final = "UIUXLogicSlice@2"
UIUX_LOGIC_SLICE_V2_VERSION: Final = "2.0.0"
UIUX_LOGIC_SLICE_V2_SCHEMA: Final = "ui-ux-logic-slice/v2"

UIUX_FORMALIZATION_ADAPTER_V2_INTERFACE: Final = "UIUXFormalizationAdapter@2"
UIUX_FORMALIZATION_ADAPTER_V2_VERSION: Final = "2.0.0"
UIUX_FORMALIZATION_ADAPTER_V2_SCHEMA: Final = "ui-ux-formalization-adapter/v2"

UIUX_DOMAIN_ID: Final = "ui_ux_ir"
UIUX_PACKAGE_NAME: Final = "ui_ux_ir"
UIUX_PACKAGE_RELATIVE: Final = "ipfs_datasets_py/logic/ui_ux_ir"
UIUX_SUPERPROJECT_PACKAGE_RELATIVE: Final = (
    "ipfs_datasets_py/ipfs_datasets_py/logic/ui_ux_ir"
)
UIUX_OWNER_ID: Final = "domain:ui_ux_ir"
UIUX_TASK_ID: Final = "LFP2-026"
UIUX_GOAL_ID: Final = "LFP2-G050"

# Disposition codes (stable wire values).
SOURCE_MISSING: Final = "source_missing"
SOURCE_NOT_IN_PINNED_REVISION: Final = "source_not_in_pinned_revision"
SOURCE_PRESENT_IN_PINNED_REVISION: Final = "source_present_in_pinned_revision"
DECLARATION_ONLY: Final = "declaration_only"
REASON_ABSENT_PACKAGE: Final = (
    "ui_ux_ir package absent from pinned datasets revision"
)
REASON_PRESENT_PACKAGE: Final = (
    "ui_ux_ir package present at exact reviewed path"
)

# Owner-scoped requirement surfaces recorded by UIUXLogicSlice@2.
# Aligned with plan Workstream 5 ui_ux_ir obligations and LFP2-026 effects.
REQUIREMENT_SURFACE_IDS: Final[tuple[str, ...]] = (
    "accessibility",
    "authorization",
    "interaction_event",
    "observable_state",
    "ontology_frame",
    "workflow",
)

# Owner-scoped adapter surfaces for the single derived adapter gap.
ADAPTER_SCOPE_IDS: Final[tuple[str, ...]] = (
    "accessibility",
    "authorization",
    "component_frame",
    "event",
    "navigation_state",
    "permission",
    "privacy",
    "runtime_journey",
    "tdfol_dcec",
    "workflow",
)

# Acceptance criteria required of the derived adapter gap.
ADAPTER_GAP_ACCEPTANCE_REQUIREMENTS: Final[tuple[str, ...]] = (
    "declared_syntax_parsing",
    "frame_logic_alias_canonicalization",
    "typed_structural_round_trips",
)

# Explicit non-acceptance: token-presence greps are never sufficient.
ADAPTER_GAP_REJECTED_ACCEPTANCE: Final[tuple[str, ...]] = (
    "token_presence",
)

# frame_logic dual-read aliases sealed by the family registry.
FRAME_LOGIC_FAMILY_ID: Final = "frame_logic"
FRAME_LOGIC_ALIASES: Final[tuple[str, ...]] = ("FLogic", "F-logic")

_DIGEST_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_SAFE_REL_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,511}$")

# Marker files that count as a real package root (not an empty directory).
_PACKAGE_MARKERS: Final[tuple[str, ...]] = (
    "__init__.py",
    "py.typed",
    "README.md",
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class UIUXLogicGateV2Error(ValueError):
    """Raised when the UI/UX logic gate v2 cannot complete safely."""

    def __init__(self, message: str, *, code: str = "ui_ux.gate_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


class UIUXSourceMissingError(UIUXLogicGateV2Error):
    """Raised when formalization is requested while source is missing."""

    def __init__(self, message: str = "") -> None:
        super().__init__(
            message
            or (
                "ui_ux_ir is not present in the pinned revision; "
                "formalization is declaration-only until exact source import"
            ),
            code="ui_ux.source_missing",
        )


class UIUXPackageWriteForbiddenError(UIUXLogicGateV2Error):
    """Raised if a caller attempts to create or mutate ui_ux_ir via the gate."""

    def __init__(self, message: str = "") -> None:
        super().__init__(
            message
            or "UIUXSourceGate@2 must never create, copy, or edit ui_ux_ir",
            code="ui_ux.package_write_forbidden",
        )


class UIUXFreeFormRejectedError(UIUXLogicGateV2Error):
    """Raised when free-form text is offered instead of typed structure."""

    def __init__(self, message: str = "") -> None:
        super().__init__(
            message
            or "free-form token presence is rejected; require declared-syntax parsing",
            code="ui_ux.free_form_rejected",
        )


class UIUXSliceAdmissionError(UIUXLogicGateV2Error):
    """Raised when a UIUXLogicSlice@2 cannot be admitted for backend use."""

    def __init__(self, message: str = "") -> None:
        super().__init__(
            message
            or "UIUXLogicSlice@2 cannot admit routes while source is missing",
            code="ui_ux.slice_not_admitted",
        )


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SourcePresence(StrEnum):
    """Whether the exact UI/UX package is present under the scan root."""

    ABSENT = "absent"
    PRESENT = "present"


class GateDisposition(StrEnum):
    """Top-level gate outcome for one scan."""

    DECLARATION_ONLY = "declaration_only"
    EMIT_ADAPTER_GAP = "emit_adapter_gap"


class RequirementSurface(StrEnum):
    """Owner-scoped requirement surfaces recorded by UIUXLogicSlice@2."""

    ACCESSIBILITY = "accessibility"
    AUTHORIZATION = "authorization"
    INTERACTION_EVENT = "interaction_event"
    OBSERVABLE_STATE = "observable_state"
    ONTOLOGY_FRAME = "ontology_frame"
    WORKFLOW = "workflow"


class AdapterScope(StrEnum):
    """Owner-scoped surfaces the derived adapter gap must cover."""

    ACCESSIBILITY = "accessibility"
    AUTHORIZATION = "authorization"
    COMPONENT_FRAME = "component_frame"
    EVENT = "event"
    NAVIGATION_STATE = "navigation_state"
    PERMISSION = "permission"
    PRIVACY = "privacy"
    RUNTIME_JOURNEY = "runtime_journey"
    TDFOL_DCEC = "tdfol_dcec"
    WORKFLOW = "workflow"


class SliceStatus(StrEnum):
    """Admission status of a UIUXLogicSlice@2 record."""

    DECLARATION_ONLY = "declaration_only"
    ADAPTER_GAP = "adapter_gap"
    ADMITTED = "admitted"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise UIUXLogicGateV2Error(
            f"{field_name} must be a non-empty trimmed string",
            code="ui_ux.malformed",
        )
    if "\x00" in value:
        raise UIUXLogicGateV2Error(
            f"{field_name} must not contain NUL bytes",
            code="ui_ux.malformed",
        )
    return value


def _optional_text(value: object, field_name: str) -> str:
    if value in (None, ""):
        return ""
    return _text(value, field_name)


def _safe_relative(value: object, field_name: str) -> str:
    text = _text(value, field_name).replace("\\", "/")
    if text.startswith("/") or ".." in Path(text).parts:
        raise UIUXLogicGateV2Error(
            f"{field_name} must be a normalized repository-relative POSIX path",
            code="ui_ux.unsafe_path",
        )
    if not _SAFE_REL_RE.fullmatch(text):
        raise UIUXLogicGateV2Error(
            f"{field_name} has an unsafe relative path form: {text!r}",
            code="ui_ux.unsafe_path",
        )
    return text


def _digest_hex(value: Mapping[str, Any]) -> str:
    digest = stable_digest(dict(value))
    if not _DIGEST_RE.fullmatch(digest):
        raise UIUXLogicGateV2Error(
            "content digest must be a 64-char lowercase hex SHA-256",
            code="ui_ux.digest",
        )
    return digest


def _sorted_unique(values: Sequence[str], field_name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise UIUXLogicGateV2Error(
            f"{field_name} must be a sequence of strings",
            code="ui_ux.malformed",
        )
    items = tuple(_text(item, f"{field_name} item") for item in values)
    if len(set(items)) != len(items):
        raise UIUXLogicGateV2Error(
            f"{field_name} must not contain duplicates",
            code="ui_ux.malformed",
        )
    return tuple(sorted(items))


def default_logic_package_root(start: Path | None = None) -> Path:
    """Resolve the ``logic/`` package root without importing production parsers."""

    if start is not None:
        candidate = Path(start).resolve()
        if candidate.name == "logic" and candidate.is_dir():
            return candidate
        nested = candidate / "ipfs_datasets_py" / "logic"
        if nested.is_dir():
            return nested.resolve()
        nested = candidate / "logic"
        if nested.is_dir():
            return nested.resolve()
        raise UIUXLogicGateV2Error(
            f"unable to resolve logic package root from {start!s}",
            code="ui_ux.root",
        )

    here = Path(__file__).resolve()
    # .../ipfs_datasets_py/logic/conformance/ui_ux_logic_gate_v2.py -> logic/
    logic_root = here.parents[1]
    if logic_root.name == "logic":
        return logic_root
    raise UIUXLogicGateV2Error(
        "unable to resolve logic package root from gate module",
        code="ui_ux.root",
    )


def default_datasets_package_root(logic_root: Path | None = None) -> Path:
    """Resolve the nested ``ipfs_datasets_py`` package root containing ``logic/``."""

    root = default_logic_package_root(logic_root) if logic_root is None else Path(logic_root)
    package = root.parent
    if package.name != "ipfs_datasets_py":
        raise UIUXLogicGateV2Error(
            f"expected logic parent named ipfs_datasets_py, got {package.name!r}",
            code="ui_ux.root",
        )
    return package


def ui_ux_package_path(logic_root: Path | None = None) -> Path:
    """Absolute path where the exact ``ui_ux_ir`` package would live."""

    return default_logic_package_root(logic_root) / UIUX_PACKAGE_NAME


def package_is_present(package_path: Path) -> bool:
    """Return True when a real package root exists (not an empty placeholder dir)."""

    if not package_path.is_dir():
        return False
    for marker in _PACKAGE_MARKERS:
        if (package_path / marker).is_file():
            return True
    # Non-empty directory with any .py file also counts as present source.
    try:
        for child in package_path.iterdir():
            if child.is_file() and child.suffix == ".py":
                return True
            if child.is_dir() and not child.name.startswith("."):
                return True
    except OSError:
        return False
    return False


def _fingerprint_present_package(package_path: Path) -> str:
    """Content-addressed fingerprint of a present package tree (read-only)."""

    entries: list[tuple[str, int]] = []
    root = package_path.resolve()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel_path = path.relative_to(root)
        # Only skip hidden / cache segments *inside* the package, never ancestors
        # such as a supervisor worktree named ``.worktrees``.
        if any(
            part.startswith(".") or part == "__pycache__" for part in rel_path.parts
        ):
            continue
        rel = rel_path.as_posix()
        try:
            size = path.stat().st_size
        except OSError:
            size = -1
        entries.append((rel, size))
    payload = {
        "entries": [{"path": path, "size": size} for path, size in entries],
        "package": UIUX_PACKAGE_NAME,
        "schema_version": UIUX_SOURCE_IDENTITY_V2_SCHEMA,
    }
    return _digest_hex(payload)


# ---------------------------------------------------------------------------
# frame_logic alias canonicalization
# ---------------------------------------------------------------------------


def canonicalize_frame_logic_label(
    label: str,
    *,
    registry: LogicFamilyRegistry | None = None,
) -> str:
    """Canonicalize F-logic dual-read labels to ``frame_logic``.

    Accepts registry aliases such as ``FLogic`` / ``F-logic`` and the
    canonical family id. Unknown labels fail closed.
    """

    text = _text(label, "label")
    reg = registry if registry is not None else DEFAULT_REGISTRY
    try:
        family = reg.family(text)
    except (UnknownDescriptorError, LogicFamilyRegistryError) as error:
        raise UIUXLogicGateV2Error(
            f"unknown frame_logic label {text!r}; cannot canonicalize",
            code="ui_ux.unknown_family_label",
        ) from error

    family_id = family.family_id
    if family_id != FRAME_LOGIC_FAMILY_ID:
        raise UIUXLogicGateV2Error(
            f"label {text!r} resolves to {family_id!r}, not frame_logic",
            code="ui_ux.wrong_family",
        )
    return FRAME_LOGIC_FAMILY_ID


def frame_logic_alias_table(
    *,
    registry: LogicFamilyRegistry | None = None,
) -> Mapping[str, str]:
    """Return dual-read alias → ``frame_logic`` mappings used by the gate."""

    reg = registry if registry is not None else DEFAULT_REGISTRY
    table: dict[str, str] = {FRAME_LOGIC_FAMILY_ID: FRAME_LOGIC_FAMILY_ID}
    for alias in FRAME_LOGIC_ALIASES:
        table[alias] = canonicalize_frame_logic_label(alias, registry=reg)
    # Also surface any registry-declared aliases for frame_logic.
    try:
        family = reg.family(FRAME_LOGIC_FAMILY_ID)
        for alias in family.aliases:
            if isinstance(alias, str) and alias.strip():
                table[alias] = FRAME_LOGIC_FAMILY_ID
    except (UnknownDescriptorError, LogicFamilyRegistryError):
        pass
    return MappingProxyType(dict(sorted(table.items())))


# ---------------------------------------------------------------------------
# Requirement surface descriptors
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UIUXRequirementSurface:
    """One owner-scoped requirement surface recorded by the logic slice."""

    surface_id: str
    family_hint: str
    description: str
    owner_id: str = UIUX_OWNER_ID
    schema_version: str = "ui-ux-requirement-surface/v2"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "surface_id", _text(self.surface_id, "surface_id")
        )
        object.__setattr__(
            self, "family_hint", _text(self.family_hint, "family_hint")
        )
        object.__setattr__(
            self, "description", _text(self.description, "description")
        )
        object.__setattr__(self, "owner_id", _text(self.owner_id, "owner_id"))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "family_hint": self.family_hint,
            "owner_id": self.owner_id,
            "schema_version": self.schema_version,
            "surface_id": self.surface_id,
        }

    def content_digest(self) -> str:
        return _digest_hex(self.to_dict())


_REQUIREMENT_SURFACE_SPECS: Final[tuple[tuple[str, str, str], ...]] = (
    (
        "accessibility",
        "first_order",
        "Accessibility property obligations over UI structure and state.",
    ),
    (
        "authorization",
        "authorization",
        "Authorization and permission constraints over UI actions.",
    ),
    (
        "interaction_event",
        "event_calculus",
        "Interaction and event-calculus obligations for user/system events.",
    ),
    (
        "observable_state",
        "transition_system",
        "Observable navigation and runtime state transition obligations.",
    ),
    (
        "ontology_frame",
        "frame_logic",
        "Ontology/frame (F-logic) component and relation structure.",
    ),
    (
        "workflow",
        "temporal",
        "Workflow temporal obligations over multi-step UI journeys.",
    ),
)


def default_requirement_surfaces() -> tuple[UIUXRequirementSurface, ...]:
    """Return the fixed owner-scoped requirement surfaces for UI/UX v2."""

    return tuple(
        UIUXRequirementSurface(
            surface_id=surface_id,
            family_hint=family_hint,
            description=description,
        )
        for surface_id, family_hint, description in _REQUIREMENT_SURFACE_SPECS
    )


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UIUXSourceIdentity:
    """Exact source identity observed by one gate scan."""

    presence: SourcePresence
    package_relative_path: str = UIUX_PACKAGE_RELATIVE
    package_absolute_path: str = ""
    pinned_revision: str = ""
    source_fingerprint: str = ""
    marker_files: tuple[str, ...] = ()
    schema_version: str = UIUX_SOURCE_IDENTITY_V2_SCHEMA

    def __post_init__(self) -> None:
        if not isinstance(self.presence, SourcePresence):
            object.__setattr__(
                self, "presence", SourcePresence(str(self.presence))
            )
        object.__setattr__(
            self,
            "package_relative_path",
            _safe_relative(self.package_relative_path, "package_relative_path"),
        )
        object.__setattr__(
            self,
            "package_absolute_path",
            _optional_text(self.package_absolute_path, "package_absolute_path"),
        )
        object.__setattr__(
            self,
            "pinned_revision",
            _optional_text(self.pinned_revision, "pinned_revision"),
        )
        fingerprint = _optional_text(self.source_fingerprint, "source_fingerprint")
        if fingerprint and not _DIGEST_RE.fullmatch(fingerprint):
            raise UIUXLogicGateV2Error(
                "source_fingerprint must be empty or a 64-char hex SHA-256",
                code="ui_ux.digest",
            )
        object.__setattr__(self, "source_fingerprint", fingerprint)
        object.__setattr__(
            self,
            "marker_files",
            _sorted_unique(self.marker_files, "marker_files")
            if self.marker_files
            else (),
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.presence is SourcePresence.ABSENT and self.source_fingerprint:
            raise UIUXLogicGateV2Error(
                "absent source cannot carry a source_fingerprint",
                code="ui_ux.identity",
            )
        if self.presence is SourcePresence.PRESENT and not self.source_fingerprint:
            raise UIUXLogicGateV2Error(
                "present source requires a source_fingerprint",
                code="ui_ux.identity",
            )

    @property
    def is_present(self) -> bool:
        return self.presence is SourcePresence.PRESENT

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_present": self.is_present,
            "marker_files": list(self.marker_files),
            "package_absolute_path": self.package_absolute_path,
            "package_relative_path": self.package_relative_path,
            "pinned_revision": self.pinned_revision,
            "presence": self.presence.value,
            "schema_version": self.schema_version,
            "source_fingerprint": self.source_fingerprint,
        }

    def content_digest(self) -> str:
        body = {
            key: value
            for key, value in self.to_dict().items()
            if key != "package_absolute_path"
        }
        return _digest_hex(body)


@dataclass(frozen=True, slots=True)
class UIUXMatrixDisposition:
    """Matrix-aligned support/availability disposition for ``ui_ux_ir`` cells."""

    support: SupportStatus
    availability: AvailabilityStatus
    authority_ceiling: AuthorityCeiling
    reason_code: str
    notes: str = ""
    domain_id: str = UIUX_DOMAIN_ID
    unimplemented: bool = True
    refill_eligible: bool = True
    blocks_other_work: bool = False
    schema_version: str = UIUX_MATRIX_DISPOSITION_V2_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "support",
            self.support
            if isinstance(self.support, SupportStatus)
            else SupportStatus(str(self.support)),
        )
        object.__setattr__(
            self,
            "availability",
            self.availability
            if isinstance(self.availability, AvailabilityStatus)
            else AvailabilityStatus(str(self.availability)),
        )
        object.__setattr__(
            self,
            "authority_ceiling",
            self.authority_ceiling
            if isinstance(self.authority_ceiling, AuthorityCeiling)
            else AuthorityCeiling(str(self.authority_ceiling)),
        )
        object.__setattr__(self, "reason_code", _text(self.reason_code, "reason_code"))
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "domain_id", _text(self.domain_id, "domain_id"))
        if not isinstance(self.unimplemented, bool):
            raise UIUXLogicGateV2Error("unimplemented must be a boolean")
        if not isinstance(self.refill_eligible, bool):
            raise UIUXLogicGateV2Error("refill_eligible must be a boolean")
        if not isinstance(self.blocks_other_work, bool):
            raise UIUXLogicGateV2Error("blocks_other_work must be a boolean")
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        # Fail closed: source-missing requires declaration-only/unknown/unsupported.
        if (
            self.availability is AvailabilityStatus.SOURCE_MISSING
            and self.support
            not in {
                SupportStatus.DECLARATION_ONLY,
                SupportStatus.UNKNOWN,
                SupportStatus.UNSUPPORTED,
            }
        ):
            raise UIUXLogicGateV2Error(
                "source-missing availability requires declaration-only/"
                "unknown/unsupported support",
                code="ui_ux.disposition",
            )
        if (
            self.support is SupportStatus.DECLARATION_ONLY
            and self.authority_ceiling
            not in {AuthorityCeiling.NONE, AuthorityCeiling.UNKNOWN}
        ):
            raise UIUXLogicGateV2Error(
                "declaration-only disposition cannot claim non-empty authority",
                code="ui_ux.disposition",
            )
        # Absent-source disposition must never block other work.
        if (
            self.availability is AvailabilityStatus.SOURCE_MISSING
            and self.blocks_other_work
        ):
            raise UIUXLogicGateV2Error(
                "source_missing disposition must not block other work",
                code="ui_ux.disposition",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_ceiling": self.authority_ceiling.value,
            "availability": self.availability.value,
            "blocks_other_work": self.blocks_other_work,
            "domain_id": self.domain_id,
            "notes": self.notes,
            "reason_code": self.reason_code,
            "refill_eligible": self.refill_eligible,
            "schema_version": self.schema_version,
            "support": self.support.value,
            "unimplemented": self.unimplemented,
        }

    def content_digest(self) -> str:
        return _digest_hex(self.to_dict())


def absent_matrix_disposition() -> UIUXMatrixDisposition:
    """Typed disposition for the current missing-source state."""

    return UIUXMatrixDisposition(
        support=SupportStatus.DECLARATION_ONLY,
        availability=AvailabilityStatus.SOURCE_MISSING,
        authority_ceiling=AuthorityCeiling.NONE,
        reason_code=SOURCE_NOT_IN_PINNED_REVISION,
        notes=(
            "ui_ux_ir is not present in the pinned datasets revision; "
            "every UI cell is declaration-only with source_missing; "
            "other domain work is not blocked."
        ),
        unimplemented=True,
        refill_eligible=True,
        blocks_other_work=False,
    )


def present_matrix_disposition(*, notes: str = "") -> UIUXMatrixDisposition:
    """Disposition once exact source is present (still gap until adapter lands)."""

    return UIUXMatrixDisposition(
        support=SupportStatus.DECLARATION_ONLY,
        availability=AvailabilityStatus.DECLARED,
        authority_ceiling=AuthorityCeiling.NONE,
        reason_code=SOURCE_PRESENT_IN_PINNED_REVISION,
        notes=notes
        or (
            "ui_ux_ir is present in the pinned revision; emit one content-addressed "
            "owner-scoped adapter gap before upgrading matrix support."
        ),
        unimplemented=True,
        refill_eligible=True,
        blocks_other_work=False,
    )


@dataclass(frozen=True, slots=True)
class UIUXAdapterGap:
    """Exactly one content-addressed owner-scoped adapter gap."""

    gap_id: str
    source_fingerprint: str
    pinned_revision: str
    package_relative_path: str
    owner_id: str = UIUX_OWNER_ID
    adapter_interface: str = UIUX_FORMALIZATION_ADAPTER_V2_INTERFACE
    scopes: tuple[str, ...] = ADAPTER_SCOPE_IDS
    requirement_surfaces: tuple[str, ...] = REQUIREMENT_SURFACE_IDS
    acceptance_requirements: tuple[str, ...] = ADAPTER_GAP_ACCEPTANCE_REQUIREMENTS
    rejected_acceptance: tuple[str, ...] = ADAPTER_GAP_REJECTED_ACCEPTANCE
    preserve: tuple[str, ...] = (
        "authority_flags",
        "golden_vectors",
        "graph_schemas",
        "source_maps",
    )
    frame_logic_aliases: tuple[str, ...] = FRAME_LOGIC_ALIASES
    domain_id: str = UIUX_DOMAIN_ID
    schema_version: str = UIUX_ADAPTER_GAP_V2_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "gap_id", _text(self.gap_id, "gap_id"))
        object.__setattr__(
            self,
            "source_fingerprint",
            _text(self.source_fingerprint, "source_fingerprint"),
        )
        if not _DIGEST_RE.fullmatch(self.source_fingerprint):
            raise UIUXLogicGateV2Error(
                "source_fingerprint must be a 64-char hex SHA-256",
                code="ui_ux.digest",
            )
        object.__setattr__(
            self,
            "pinned_revision",
            _optional_text(self.pinned_revision, "pinned_revision"),
        )
        object.__setattr__(
            self,
            "package_relative_path",
            _safe_relative(self.package_relative_path, "package_relative_path"),
        )
        object.__setattr__(self, "owner_id", _text(self.owner_id, "owner_id"))
        object.__setattr__(
            self,
            "adapter_interface",
            _text(self.adapter_interface, "adapter_interface"),
        )
        object.__setattr__(
            self, "scopes", _sorted_unique(self.scopes, "scopes")
        )
        object.__setattr__(
            self,
            "requirement_surfaces",
            _sorted_unique(self.requirement_surfaces, "requirement_surfaces"),
        )
        object.__setattr__(
            self,
            "acceptance_requirements",
            _sorted_unique(
                self.acceptance_requirements, "acceptance_requirements"
            ),
        )
        object.__setattr__(
            self,
            "rejected_acceptance",
            _sorted_unique(self.rejected_acceptance, "rejected_acceptance"),
        )
        object.__setattr__(
            self, "preserve", _sorted_unique(self.preserve, "preserve")
        )
        object.__setattr__(
            self,
            "frame_logic_aliases",
            _sorted_unique(self.frame_logic_aliases, "frame_logic_aliases")
            if self.frame_logic_aliases
            else (),
        )
        object.__setattr__(self, "domain_id", _text(self.domain_id, "domain_id"))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        required = set(ADAPTER_GAP_ACCEPTANCE_REQUIREMENTS)
        if not required.issubset(set(self.acceptance_requirements)):
            raise UIUXLogicGateV2Error(
                "adapter gap must require declared-syntax parsing, "
                "frame_logic alias canonicalization, and typed structural round trips",
                code="ui_ux.acceptance",
            )
        if "token_presence" in self.acceptance_requirements:
            raise UIUXLogicGateV2Error(
                "token_presence is never a valid acceptance requirement",
                code="ui_ux.acceptance",
            )
        if "token_presence" not in self.rejected_acceptance:
            raise UIUXLogicGateV2Error(
                "adapter gap must explicitly reject token_presence acceptance",
                code="ui_ux.acceptance",
            )
        required_surfaces = set(REQUIREMENT_SURFACE_IDS)
        if not required_surfaces.issubset(set(self.requirement_surfaces)):
            raise UIUXLogicGateV2Error(
                "adapter gap must cover all UIUXLogicSlice@2 requirement surfaces",
                code="ui_ux.acceptance",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "acceptance_requirements": list(self.acceptance_requirements),
            "adapter_interface": self.adapter_interface,
            "domain_id": self.domain_id,
            "frame_logic_aliases": list(self.frame_logic_aliases),
            "gap_id": self.gap_id,
            "owner_id": self.owner_id,
            "package_relative_path": self.package_relative_path,
            "pinned_revision": self.pinned_revision,
            "preserve": list(self.preserve),
            "rejected_acceptance": list(self.rejected_acceptance),
            "requirement_surfaces": list(self.requirement_surfaces),
            "schema_version": self.schema_version,
            "scopes": list(self.scopes),
            "source_fingerprint": self.source_fingerprint,
        }

    def content_digest(self) -> str:
        body = {key: value for key, value in self.to_dict().items() if key != "gap_id"}
        return _digest_hex(body)


def build_adapter_gap(identity: UIUXSourceIdentity) -> UIUXAdapterGap:
    """Build the single owner-scoped adapter gap for a present source identity."""

    if not identity.is_present:
        raise UIUXLogicGateV2Error(
            "cannot emit adapter gap while source is absent",
            code="ui_ux.source_missing",
        )
    # Build a provisional gap so gap_id is derived from the same sorted wire
    # body that ``content_digest`` uses (excluding gap_id itself).
    provisional = UIUXAdapterGap(
        gap_id="ui-ux-adapter-gap:pending",
        source_fingerprint=identity.source_fingerprint,
        pinned_revision=identity.pinned_revision,
        package_relative_path=identity.package_relative_path,
        owner_id=UIUX_OWNER_ID,
        adapter_interface=UIUX_FORMALIZATION_ADAPTER_V2_INTERFACE,
        scopes=ADAPTER_SCOPE_IDS,
        requirement_surfaces=REQUIREMENT_SURFACE_IDS,
        acceptance_requirements=ADAPTER_GAP_ACCEPTANCE_REQUIREMENTS,
        rejected_acceptance=ADAPTER_GAP_REJECTED_ACCEPTANCE,
        preserve=(
            "authority_flags",
            "golden_vectors",
            "graph_schemas",
            "source_maps",
        ),
        frame_logic_aliases=FRAME_LOGIC_ALIASES,
    )
    digest = provisional.content_digest()
    gap_id = f"ui-ux-adapter-gap:{digest[:24]}"
    return UIUXAdapterGap(
        gap_id=gap_id,
        source_fingerprint=provisional.source_fingerprint,
        pinned_revision=provisional.pinned_revision,
        package_relative_path=provisional.package_relative_path,
        owner_id=provisional.owner_id,
        adapter_interface=provisional.adapter_interface,
        scopes=provisional.scopes,
        requirement_surfaces=provisional.requirement_surfaces,
        acceptance_requirements=provisional.acceptance_requirements,
        rejected_acceptance=provisional.rejected_acceptance,
        preserve=provisional.preserve,
        frame_logic_aliases=provisional.frame_logic_aliases,
    )


@dataclass(frozen=True, slots=True)
class UIUXSourceGateReceipt:
    """Content-addressed receipt for one exact-source gate scan."""

    disposition: GateDisposition
    identity: UIUXSourceIdentity
    matrix: UIUXMatrixDisposition
    adapter_gaps: tuple[UIUXAdapterGap, ...] = ()
    writes_ui_ux_ir: bool = False
    blocks_other_work: bool = False
    interface: str = UIUX_SOURCE_GATE_V2_INTERFACE
    version: str = UIUX_SOURCE_GATE_V2_VERSION
    schema_version: str = UIUX_SOURCE_RECEIPT_V2_SCHEMA
    content_digest: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, GateDisposition):
            object.__setattr__(
                self, "disposition", GateDisposition(str(self.disposition))
            )
        if not isinstance(self.identity, UIUXSourceIdentity):
            raise UIUXLogicGateV2Error("identity must be a UIUXSourceIdentity")
        if not isinstance(self.matrix, UIUXMatrixDisposition):
            raise UIUXLogicGateV2Error("matrix must be a UIUXMatrixDisposition")
        if isinstance(self.adapter_gaps, (str, bytes, bytearray)) or not isinstance(
            self.adapter_gaps, Sequence
        ):
            raise UIUXLogicGateV2Error("adapter_gaps must be a sequence")
        gaps = tuple(self.adapter_gaps)
        for gap in gaps:
            if not isinstance(gap, UIUXAdapterGap):
                raise UIUXLogicGateV2Error(
                    "adapter_gaps items must be UIUXAdapterGap"
                )
        object.__setattr__(self, "adapter_gaps", gaps)
        if not isinstance(self.writes_ui_ux_ir, bool):
            raise UIUXLogicGateV2Error("writes_ui_ux_ir must be a boolean")
        if self.writes_ui_ux_ir:
            raise UIUXLogicGateV2Error(
                "gate receipt must never claim ui_ux_ir writes",
                code="ui_ux.package_write_forbidden",
            )
        if not isinstance(self.blocks_other_work, bool):
            raise UIUXLogicGateV2Error("blocks_other_work must be a boolean")
        if self.blocks_other_work:
            raise UIUXLogicGateV2Error(
                "gate receipt must never block other work",
                code="ui_ux.blocks_other_work",
            )
        object.__setattr__(self, "interface", _text(self.interface, "interface"))
        object.__setattr__(self, "version", _text(self.version, "version"))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

        if (
            self.disposition is GateDisposition.DECLARATION_ONLY
            and self.identity.is_present
        ):
            raise UIUXLogicGateV2Error(
                "declaration-only disposition cannot accompany present source",
                code="ui_ux.receipt",
            )
        if (
            self.disposition is GateDisposition.EMIT_ADAPTER_GAP
            and not self.identity.is_present
        ):
            raise UIUXLogicGateV2Error(
                "emit-adapter-gap disposition requires present source",
                code="ui_ux.receipt",
            )
        if self.disposition is GateDisposition.DECLARATION_ONLY:
            if self.adapter_gaps:
                raise UIUXLogicGateV2Error(
                    "absent source must not emit adapter gaps",
                    code="ui_ux.receipt",
                )
            if self.matrix.reason_code != SOURCE_NOT_IN_PINNED_REVISION:
                raise UIUXLogicGateV2Error(
                    "absent source must report source_not_in_pinned_revision",
                    code="ui_ux.receipt",
                )
            if self.matrix.support is not SupportStatus.DECLARATION_ONLY:
                raise UIUXLogicGateV2Error(
                    "absent source must be declaration_only",
                    code="ui_ux.receipt",
                )
            if self.matrix.availability is not AvailabilityStatus.SOURCE_MISSING:
                raise UIUXLogicGateV2Error(
                    "absent source must be source_missing",
                    code="ui_ux.receipt",
                )
        if self.disposition is GateDisposition.EMIT_ADAPTER_GAP:
            if len(self.adapter_gaps) != 1:
                raise UIUXLogicGateV2Error(
                    "present source must emit exactly one owner-scoped adapter gap",
                    code="ui_ux.receipt",
                )

        digest = _optional_text(self.content_digest, "content_digest")
        if not digest:
            digest = _digest_hex(self._digest_body())
        elif not _DIGEST_RE.fullmatch(digest):
            raise UIUXLogicGateV2Error(
                "content_digest must be a 64-char hex SHA-256",
                code="ui_ux.digest",
            )
        object.__setattr__(self, "content_digest", digest)

    def _digest_body(self) -> dict[str, Any]:
        # Absolute package paths are observational only and must not affect the
        # content-addressed identity of the gate receipt.
        identity_body = {
            key: value
            for key, value in self.identity.to_dict().items()
            if key != "package_absolute_path"
        }
        return {
            "adapter_gaps": [gap.to_dict() for gap in self.adapter_gaps],
            "blocks_other_work": self.blocks_other_work,
            "disposition": self.disposition.value,
            "identity": identity_body,
            "interface": self.interface,
            "matrix": self.matrix.to_dict(),
            "schema_version": self.schema_version,
            "version": self.version,
            "writes_ui_ux_ir": self.writes_ui_ux_ir,
        }

    def to_dict(self) -> dict[str, Any]:
        body = self._digest_body()
        body["content_digest"] = self.content_digest
        return body

    def recompute_content_digest(self) -> str:
        return _digest_hex(self._digest_body())


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UIUXSourceGate:
    """``UIUXSourceGate@2`` exact-source scanner for ``ui_ux_ir``."""

    INTERFACE: ClassVar[str] = UIUX_SOURCE_GATE_V2_INTERFACE
    VERSION: ClassVar[str] = UIUX_SOURCE_GATE_V2_VERSION

    logic_root: Path | None = None
    pinned_revision: str = ""
    package_relative_path: str = UIUX_PACKAGE_RELATIVE

    @property
    def interface(self) -> str:
        return self.INTERFACE

    @property
    def version(self) -> str:
        return self.VERSION

    def observe_identity(self) -> UIUXSourceIdentity:
        """Observe package presence under the configured logic root."""

        logic_root = default_logic_package_root(self.logic_root)
        package_path = logic_root / UIUX_PACKAGE_NAME
        present = package_is_present(package_path)
        markers: list[str] = []
        fingerprint = ""
        if present:
            for marker in _PACKAGE_MARKERS:
                if (package_path / marker).is_file():
                    markers.append(marker)
            fingerprint = _fingerprint_present_package(package_path)
        return UIUXSourceIdentity(
            presence=SourcePresence.PRESENT if present else SourcePresence.ABSENT,
            package_relative_path=self.package_relative_path,
            package_absolute_path=str(package_path.resolve()),
            pinned_revision=_optional_text(self.pinned_revision, "pinned_revision"),
            source_fingerprint=fingerprint,
            marker_files=tuple(markers),
        )

    def scan(self) -> UIUXSourceGateReceipt:
        """Scan once and return a content-addressed gate receipt.

        Never writes ``ui_ux_ir``. Absent source yields declaration-only /
        ``source_missing`` without blocking other work. Present source yields
        exactly one content-addressed owner-scoped adapter gap.
        """

        identity = self.observe_identity()
        if not identity.is_present:
            return UIUXSourceGateReceipt(
                disposition=GateDisposition.DECLARATION_ONLY,
                identity=identity,
                matrix=absent_matrix_disposition(),
                adapter_gaps=(),
                writes_ui_ux_ir=False,
                blocks_other_work=False,
            )
        gap = build_adapter_gap(identity)
        return UIUXSourceGateReceipt(
            disposition=GateDisposition.EMIT_ADAPTER_GAP,
            identity=identity,
            matrix=present_matrix_disposition(),
            adapter_gaps=(gap,),
            writes_ui_ux_ir=False,
            blocks_other_work=False,
        )

    def forbid_package_write(self, path: Path | str) -> None:
        """Fail closed if a caller attempts to write under ``ui_ux_ir``."""

        target = Path(path).resolve()
        package = ui_ux_package_path(self.logic_root).resolve()
        try:
            target.relative_to(package)
        except ValueError:
            return
        raise UIUXPackageWriteForbiddenError(
            f"refusing write under ui_ux_ir path {target}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": UIUX_DOMAIN_ID,
            "interface": self.interface,
            "package_relative_path": self.package_relative_path,
            "pinned_revision": self.pinned_revision,
            "version": self.version,
        }


def scan_ui_ux_source_gate_v2(
    *,
    logic_root: Path | None = None,
    pinned_revision: str = "",
    package_relative_path: str = UIUX_PACKAGE_RELATIVE,
) -> UIUXSourceGateReceipt:
    """Convenience entrypoint for a single exact-source gate scan."""

    return UIUXSourceGate(
        logic_root=logic_root,
        pinned_revision=pinned_revision,
        package_relative_path=package_relative_path,
    ).scan()


def adapter_gaps_for(
    receipt: UIUXSourceGateReceipt,
) -> tuple[UIUXAdapterGap, ...]:
    """Return adapter gaps from a receipt (0 or 1)."""

    if not isinstance(receipt, UIUXSourceGateReceipt):
        raise UIUXLogicGateV2Error("receipt must be a UIUXSourceGateReceipt")
    return receipt.adapter_gaps


# ---------------------------------------------------------------------------
# Formalization adapter interface (declaration until source import)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UIUXFormalizationAdapter:
    """``UIUXFormalizationAdapter@2`` contract surface for the derived gap.

    This class does **not** implement domain formalization.  It declares the
    adapter interface identity, required scopes, and fail-closed behaviour
    while ``ui_ux_ir`` is absent.  The owner-scoped adapter gap owns the real
    adapter implementation after exact source import.
    """

    INTERFACE: ClassVar[str] = UIUX_FORMALIZATION_ADAPTER_V2_INTERFACE
    VERSION: ClassVar[str] = UIUX_FORMALIZATION_ADAPTER_V2_VERSION

    gate: UIUXSourceGate | None = None
    registry: LogicFamilyRegistry | None = None

    @property
    def interface(self) -> str:
        return self.INTERFACE

    @property
    def version(self) -> str:
        return self.VERSION

    @property
    def domain(self) -> str:
        return UIUX_DOMAIN_ID

    @property
    def scopes(self) -> tuple[str, ...]:
        return ADAPTER_SCOPE_IDS

    def require_source_present(self) -> UIUXSourceIdentity:
        """Fail closed unless exact source is present under the gate root."""

        gate = self.gate or UIUXSourceGate()
        identity = gate.observe_identity()
        if not identity.is_present:
            raise UIUXSourceMissingError()
        return identity

    def formalize(self, document: Any = None) -> Mapping[str, Any]:
        """Refuse formalization until exact source import and derived adapter land.

        Token-presence / free-form payloads are always rejected.
        """

        if isinstance(document, (str, bytes, bytearray)):
            raise UIUXFreeFormRejectedError()
        self.require_source_present()
        raise UIUXLogicGateV2Error(
            "UIUXFormalizationAdapter@2 is a declaration-only interface; "
            "the owner-scoped adapter gap must implement formalization after "
            "exact source import",
            code="ui_ux.adapter_not_implemented",
        )

    def canonicalize_family_label(self, label: str) -> str:
        """Canonicalize dual-read F-logic labels for adapter acceptance tests."""

        return canonicalize_frame_logic_label(label, registry=self.registry)

    def acceptance_contract(self) -> Mapping[str, Any]:
        """Machine-readable acceptance contract for the owner-scoped adapter gap."""

        return MappingProxyType(
            {
                "adapter_interface": self.interface,
                "domain": self.domain,
                "frame_logic_aliases": dict(
                    frame_logic_alias_table(registry=self.registry)
                ),
                "rejected_acceptance": list(ADAPTER_GAP_REJECTED_ACCEPTANCE),
                "required_acceptance": list(ADAPTER_GAP_ACCEPTANCE_REQUIREMENTS),
                "requirement_surfaces": list(REQUIREMENT_SURFACE_IDS),
                "scopes": list(self.scopes),
                "version": self.version,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "interface": self.interface,
            "schema_version": UIUX_FORMALIZATION_ADAPTER_V2_SCHEMA,
            "scopes": list(self.scopes),
            "version": self.version,
        }


# ---------------------------------------------------------------------------
# UIUXLogicSlice@2
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UIUXLogicSlice:
    """``UIUXLogicSlice@2`` exact-source-gated UI/accessibility logic slice.

    Records the owner-scoped requirement surfaces and the gate disposition.
    Never admits backend routes while source is missing; never invents
    ``ui_ux_ir``.
    """

    INTERFACE: ClassVar[str] = UIUX_LOGIC_SLICE_V2_INTERFACE
    VERSION: ClassVar[str] = UIUX_LOGIC_SLICE_V2_VERSION

    status: SliceStatus
    identity: UIUXSourceIdentity
    matrix: UIUXMatrixDisposition
    requirement_surfaces: tuple[UIUXRequirementSurface, ...]
    adapter_gaps: tuple[UIUXAdapterGap, ...] = ()
    gate_receipt_digest: str = ""
    blocks_other_work: bool = False
    domain_id: str = UIUX_DOMAIN_ID
    owner_id: str = UIUX_OWNER_ID
    task_id: str = UIUX_TASK_ID
    goal_id: str = UIUX_GOAL_ID
    interface: str = UIUX_LOGIC_SLICE_V2_INTERFACE
    version: str = UIUX_LOGIC_SLICE_V2_VERSION
    schema_version: str = UIUX_LOGIC_SLICE_V2_SCHEMA
    content_digest: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.status, SliceStatus):
            object.__setattr__(self, "status", SliceStatus(str(self.status)))
        if not isinstance(self.identity, UIUXSourceIdentity):
            raise UIUXLogicGateV2Error("identity must be a UIUXSourceIdentity")
        if not isinstance(self.matrix, UIUXMatrixDisposition):
            raise UIUXLogicGateV2Error("matrix must be a UIUXMatrixDisposition")
        if isinstance(
            self.requirement_surfaces, (str, bytes, bytearray)
        ) or not isinstance(self.requirement_surfaces, Sequence):
            raise UIUXLogicGateV2Error("requirement_surfaces must be a sequence")
        surfaces = tuple(self.requirement_surfaces)
        for surface in surfaces:
            if not isinstance(surface, UIUXRequirementSurface):
                raise UIUXLogicGateV2Error(
                    "requirement_surfaces items must be UIUXRequirementSurface"
                )
        surface_ids = tuple(item.surface_id for item in surfaces)
        if set(surface_ids) != set(REQUIREMENT_SURFACE_IDS):
            raise UIUXLogicGateV2Error(
                "UIUXLogicSlice@2 must record exactly the fixed requirement surfaces",
                code="ui_ux.slice",
            )
        object.__setattr__(
            self,
            "requirement_surfaces",
            tuple(sorted(surfaces, key=lambda item: item.surface_id)),
        )
        if isinstance(self.adapter_gaps, (str, bytes, bytearray)) or not isinstance(
            self.adapter_gaps, Sequence
        ):
            raise UIUXLogicGateV2Error("adapter_gaps must be a sequence")
        gaps = tuple(self.adapter_gaps)
        for gap in gaps:
            if not isinstance(gap, UIUXAdapterGap):
                raise UIUXLogicGateV2Error(
                    "adapter_gaps items must be UIUXAdapterGap"
                )
        object.__setattr__(self, "adapter_gaps", gaps)
        object.__setattr__(
            self,
            "gate_receipt_digest",
            _optional_text(self.gate_receipt_digest, "gate_receipt_digest"),
        )
        if self.gate_receipt_digest and not _DIGEST_RE.fullmatch(
            self.gate_receipt_digest
        ):
            raise UIUXLogicGateV2Error(
                "gate_receipt_digest must be empty or a 64-char hex SHA-256",
                code="ui_ux.digest",
            )
        if not isinstance(self.blocks_other_work, bool):
            raise UIUXLogicGateV2Error("blocks_other_work must be a boolean")
        if self.blocks_other_work:
            raise UIUXLogicGateV2Error(
                "UIUXLogicSlice@2 must never block other work",
                code="ui_ux.blocks_other_work",
            )
        object.__setattr__(self, "domain_id", _text(self.domain_id, "domain_id"))
        object.__setattr__(self, "owner_id", _text(self.owner_id, "owner_id"))
        object.__setattr__(self, "task_id", _text(self.task_id, "task_id"))
        object.__setattr__(self, "goal_id", _text(self.goal_id, "goal_id"))
        object.__setattr__(self, "interface", _text(self.interface, "interface"))
        object.__setattr__(self, "version", _text(self.version, "version"))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

        if self.status is SliceStatus.DECLARATION_ONLY:
            if self.identity.is_present:
                raise UIUXLogicGateV2Error(
                    "declaration_only slice status requires absent source",
                    code="ui_ux.slice",
                )
            if self.adapter_gaps:
                raise UIUXLogicGateV2Error(
                    "declaration_only slice must not carry adapter gaps",
                    code="ui_ux.slice",
                )
            if self.matrix.availability is not AvailabilityStatus.SOURCE_MISSING:
                raise UIUXLogicGateV2Error(
                    "declaration_only slice requires source_missing availability",
                    code="ui_ux.slice",
                )
            if self.matrix.support is not SupportStatus.DECLARATION_ONLY:
                raise UIUXLogicGateV2Error(
                    "declaration_only slice requires declaration_only support",
                    code="ui_ux.slice",
                )
        if self.status is SliceStatus.ADAPTER_GAP:
            if not self.identity.is_present:
                raise UIUXLogicGateV2Error(
                    "adapter_gap slice status requires present source",
                    code="ui_ux.slice",
                )
            if len(self.adapter_gaps) != 1:
                raise UIUXLogicGateV2Error(
                    "adapter_gap slice must carry exactly one adapter gap",
                    code="ui_ux.slice",
                )
        if self.status is SliceStatus.ADMITTED:
            raise UIUXLogicGateV2Error(
                "UIUXLogicSlice@2 cannot be admitted until the adapter gap is closed",
                code="ui_ux.slice_not_admitted",
            )

        digest = _optional_text(self.content_digest, "content_digest")
        if not digest:
            digest = _digest_hex(self._digest_body())
        elif not _DIGEST_RE.fullmatch(digest):
            raise UIUXLogicGateV2Error(
                "content_digest must be a 64-char hex SHA-256",
                code="ui_ux.digest",
            )
        object.__setattr__(self, "content_digest", digest)

    def _digest_body(self) -> dict[str, Any]:
        identity_body = {
            key: value
            for key, value in self.identity.to_dict().items()
            if key != "package_absolute_path"
        }
        return {
            "adapter_gaps": [gap.to_dict() for gap in self.adapter_gaps],
            "blocks_other_work": self.blocks_other_work,
            "domain_id": self.domain_id,
            "gate_receipt_digest": self.gate_receipt_digest,
            "goal_id": self.goal_id,
            "identity": identity_body,
            "interface": self.interface,
            "matrix": self.matrix.to_dict(),
            "owner_id": self.owner_id,
            "requirement_surfaces": [
                surface.to_dict() for surface in self.requirement_surfaces
            ],
            "schema_version": self.schema_version,
            "status": self.status.value,
            "task_id": self.task_id,
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        body = self._digest_body()
        body["content_digest"] = self.content_digest
        return body

    def recompute_content_digest(self) -> str:
        return _digest_hex(self._digest_body())

    @property
    def is_admitted(self) -> bool:
        return self.status is SliceStatus.ADMITTED

    @property
    def is_declaration_only(self) -> bool:
        return self.status is SliceStatus.DECLARATION_ONLY

    def require_admitted(self) -> None:
        """Fail closed: UI routes cannot be admitted until adapter lands."""

        raise UIUXSliceAdmissionError(
            "UIUXLogicSlice@2 is not admitted; source is "
            f"{self.identity.presence.value} with status {self.status.value}"
        )

    def surface_ids(self) -> tuple[str, ...]:
        return tuple(surface.surface_id for surface in self.requirement_surfaces)


@dataclass(frozen=True, slots=True)
class UIUXLogicSliceConnector:
    """Producer for ``UIUXLogicSlice@2`` from an exact-source gate scan."""

    INTERFACE: ClassVar[str] = UIUX_LOGIC_SLICE_V2_INTERFACE
    VERSION: ClassVar[str] = UIUX_LOGIC_SLICE_V2_VERSION

    gate: UIUXSourceGate | None = None

    @property
    def interface(self) -> str:
        return self.INTERFACE

    @property
    def version(self) -> str:
        return self.VERSION

    def connect(self) -> UIUXLogicSlice:
        """Scan the gate and project a typed UIUXLogicSlice@2."""

        gate = self.gate or UIUXSourceGate()
        receipt = gate.scan()
        surfaces = default_requirement_surfaces()
        if receipt.disposition is GateDisposition.DECLARATION_ONLY:
            status = SliceStatus.DECLARATION_ONLY
        else:
            status = SliceStatus.ADAPTER_GAP
        return UIUXLogicSlice(
            status=status,
            identity=receipt.identity,
            matrix=receipt.matrix,
            requirement_surfaces=surfaces,
            adapter_gaps=receipt.adapter_gaps,
            gate_receipt_digest=receipt.content_digest,
            blocks_other_work=False,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": UIUX_DOMAIN_ID,
            "interface": self.interface,
            "owner_id": UIUX_OWNER_ID,
            "task_id": UIUX_TASK_ID,
            "version": self.version,
        }


def build_ui_ux_logic_slice_v2(
    *,
    logic_root: Path | None = None,
    pinned_revision: str = "",
    package_relative_path: str = UIUX_PACKAGE_RELATIVE,
) -> UIUXLogicSlice:
    """Convenience entrypoint for a single UIUXLogicSlice@2 projection."""

    gate = UIUXSourceGate(
        logic_root=logic_root,
        pinned_revision=pinned_revision,
        package_relative_path=package_relative_path,
    )
    return UIUXLogicSliceConnector(gate=gate).connect()


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    "ADAPTER_GAP_ACCEPTANCE_REQUIREMENTS",
    "ADAPTER_GAP_REJECTED_ACCEPTANCE",
    "ADAPTER_SCOPE_IDS",
    "DECLARATION_ONLY",
    "FRAME_LOGIC_ALIASES",
    "FRAME_LOGIC_FAMILY_ID",
    "REQUIREMENT_SURFACE_IDS",
    "SOURCE_MISSING",
    "SOURCE_NOT_IN_PINNED_REVISION",
    "SOURCE_PRESENT_IN_PINNED_REVISION",
    "UIUX_ADAPTER_GAP_V2_SCHEMA",
    "UIUX_DOMAIN_ID",
    "UIUX_FORMALIZATION_ADAPTER_V2_INTERFACE",
    "UIUX_FORMALIZATION_ADAPTER_V2_VERSION",
    "UIUX_GOAL_ID",
    "UIUX_LOGIC_SLICE_V2_INTERFACE",
    "UIUX_LOGIC_SLICE_V2_VERSION",
    "UIUX_OWNER_ID",
    "UIUX_PACKAGE_NAME",
    "UIUX_PACKAGE_RELATIVE",
    "UIUX_SOURCE_GATE_V2_INTERFACE",
    "UIUX_SOURCE_GATE_V2_VERSION",
    "UIUX_SUPERPROJECT_PACKAGE_RELATIVE",
    "UIUX_TASK_ID",
    "AdapterScope",
    "GateDisposition",
    "RequirementSurface",
    "SliceStatus",
    "SourcePresence",
    "UIUXAdapterGap",
    "UIUXFormalizationAdapter",
    "UIUXFreeFormRejectedError",
    "UIUXLogicGateV2Error",
    "UIUXLogicSlice",
    "UIUXLogicSliceConnector",
    "UIUXMatrixDisposition",
    "UIUXPackageWriteForbiddenError",
    "UIUXRequirementSurface",
    "UIUXSliceAdmissionError",
    "UIUXSourceGate",
    "UIUXSourceGateReceipt",
    "UIUXSourceIdentity",
    "UIUXSourceMissingError",
    "absent_matrix_disposition",
    "adapter_gaps_for",
    "build_adapter_gap",
    "build_ui_ux_logic_slice_v2",
    "canonicalize_frame_logic_label",
    "default_datasets_package_root",
    "default_logic_package_root",
    "default_requirement_surfaces",
    "frame_logic_alias_table",
    "package_is_present",
    "present_matrix_disposition",
    "scan_ui_ux_source_gate_v2",
    "ui_ux_package_path",
]
