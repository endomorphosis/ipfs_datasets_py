"""Rule- and prior-art-aware filing package compiler (PATLAW-153).

Assembles a content-addressed filing package and operator checklist from
immutable reviewed inputs (original DOCX/PDF, drawings inventory, proposed
ADS fields, forms/fees, priority/inventorship/new-matter/nonpublication/
export/IDS review items, filing-obligation packs, and prior-art coverage
signoff) without asserting human certifications, signing, paying, or filing.

Design invariants
-----------------
* Output **distinguishes** four artifact families:

  - ``proposed_metadata`` (e.g. proposed ADS fields — not filed facts)
  - ``original_files`` (source DOCX/PDF and similar native roots)
  - ``rendered_derivatives`` (PDF conversions and other renderings)
  - ``operator_checklist`` (forms/fees and named human-review items)

* Package digest is derived only from **material** inputs. Any material
  change yields a new digest and **invalidates** any prior approval bound
  to the old digest.
* Reaching ``validated`` state is fail-closed: missing or stale mandatory
  rules, unresolved prior-art coverage, digest mismatch, or required
  human confirmation still open blocks validation.
* This module never signs, pays, files, automates Patent Center, selects
  legal strategy, or claims USPTO validation of the package.
* Signatures, Rule 11.18 certifications, fees, and Submit remain natural-
  person actions outside this processor.

Conflict policy (PATLAW-153): own the package compiler, golden manifest
fixture, and unit tests only.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Final, Mapping, Sequence

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
    ReviewState,
    canonical_json,
    is_private_classification,
    requires_quarantine,
)

# ---------------------------------------------------------------------------
# Versions / interface
# ---------------------------------------------------------------------------

FILING_PACKAGE_SCHEMA_VERSION: Final = "uspto.filing-package.v1"
FILING_PACKAGE_INTERFACE: Final = "FilingPackageCompiler@1"
FILING_PACKAGE_RULESET_VERSION: Final = "filing-package-rules@1"
PARSER_VERSION: Final = "patlaw-153.filing-package.v1"

OUTPUT_KIND_FILING_PACKAGE: Final = "filing_package_manifest"
OUTPUT_KIND_PACKAGE_APPROVAL: Final = "filing_package_approval"

FILING_PACKAGE_DISCLAIMER: Final = (
    "This filing package is decision-support for a human Patent Center "
    "handoff. It never signs, pays, files, certifies under 37 C.F.R. 11.18, "
    "or validates USPTO acceptance. Proposed metadata is not filed fact. "
    "Rendered derivatives are not interchangeable with original files. "
    "Operator checklist items require natural-person confirmation."
)

DEFAULT_MAX_FILES: Final = 512
DEFAULT_MAX_ADS_FIELDS: Final = 256
DEFAULT_MAX_DRAWINGS: Final = 512
DEFAULT_MAX_CHECKLIST: Final = 512
DEFAULT_MAX_WARNINGS: Final = 256
DEFAULT_MAX_REASON_CODES: Final = 128
DEFAULT_MAX_BLOCK_REASONS: Final = 64
DEFAULT_MAX_SOURCE_ROOTS: Final = 64

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_ISO_UTC_RE = re.compile(
    r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z"
)

# Operations this compiler must never perform successfully.
FORBIDDEN_PACKAGE_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        "sign",
        "apply_signature",
        "pay",
        "pay_fee",
        "file",
        "file_application",
        "file_response",
        "submit",
        "perform_final_submission",
        "mark_submitted",
        "mark_as_submitted",
        "set_submitted",
        "automate_patent_center",
        "scrape_authenticated_patent_center",
        "read_browser_profile_or_session_storage",
        "store_credentials_or_cookies",
        "claim_patent_center_validation",
        "assert_human_certification",
        "select_legal_strategy",
        "fabricate_acknowledgement",
        "fabricate_payment_receipt",
        "fabricate_receipt",
    }
)

# Mandatory operator-checklist categories that must appear for new-application
# packages (review items from the PATLAW-153 effects statement).
MANDATORY_CHECKLIST_CATEGORIES: Final[frozenset[str]] = frozenset(
    {
        "forms",
        "fees",
        "priority",
        "inventorship",
        "new_matter",
        "nonpublication",
        "export_control",
        "ids",
    }
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class FilingPackageState(str, Enum):
    """Lifecycle states owned by the package compiler.

    Downstream handoff (PATLAW-154) extends beyond ``validated`` into
    human-approved / exported / user-submitted / receipt-verified. This
    module only advances as far as ``validated`` or ``invalidated``.
    """

    DRAFT = "draft"
    VALIDATED = "validated"
    INVALIDATED = "invalidated"


class PackageArtifactFamily(str, Enum):
    """Four distinguished output families (acceptance criterion)."""

    PROPOSED_METADATA = "proposed_metadata"
    ORIGINAL_FILE = "original_file"
    RENDERED_DERIVATIVE = "rendered_derivative"
    OPERATOR_CHECKLIST = "operator_checklist"


class OriginalFileRole(str, Enum):
    SPECIFICATION = "specification"
    CLAIMS = "claims"
    DRAWINGS = "drawings"
    ADS = "ads"
    SEQUENCE_LISTING = "sequence_listing"
    DECLARATION = "declaration"
    OTHER = "other"
    UNKNOWN = "unknown"


class MediaKind(str, Enum):
    DOCX = "docx"
    PDF = "pdf"
    IMAGE = "image"
    XML = "xml"
    TXT = "txt"
    OTHER = "other"
    UNKNOWN = "unknown"


class ChecklistCategory(str, Enum):
    FORMS = "forms"
    FEES = "fees"
    PRIORITY = "priority"
    INVENTORSHIP = "inventorship"
    NEW_MATTER = "new_matter"
    NONPUBLICATION = "nonpublication"
    EXPORT_CONTROL = "export_control"
    IDS = "ids"
    DRAWINGS = "drawings"
    SIGNATURE = "signature"
    CERTIFICATION = "certification"
    OTHER = "other"


class ValidationBlockReason(str, Enum):
    """Why a package cannot enter ``validated`` state (fail-closed)."""

    MISSING_MANDATORY_RULES = "missing_mandatory_rules"
    STALE_MANDATORY_RULES = "stale_mandatory_rules"
    UNRESOLVED_PRIOR_ART = "unresolved_prior_art"
    DIGEST_MISMATCH = "digest_mismatch"
    HUMAN_CONFIRMATION_REQUIRED = "human_confirmation_required"
    MISSING_ORIGINAL_FILES = "missing_original_files"
    MISSING_CHECKLIST_CATEGORIES = "missing_checklist_categories"
    QUARANTINE_BLOCK = "quarantine_block"
    RULE_PACK_NOT_ACTIVE = "rule_pack_not_active"
    PRIOR_ART_SIGNOFF_MISSING = "prior_art_signoff_missing"
    APPROVAL_DIGEST_MISMATCH = "approval_digest_mismatch"
    MATERIAL_INPUTS_CHANGED = "material_inputs_changed"
    EMPTY_PACKAGE = "empty_package"


class FilingPackageReasonCode(str, Enum):
    PACKAGE_COMPILED = "package_compiled"
    PACKAGE_VALIDATED = "package_validated"
    PACKAGE_DRAFT = "package_draft"
    PACKAGE_INVALIDATED = "package_invalidated"
    MATERIAL_DIGEST_COMPUTED = "material_digest_computed"
    RULES_BOUND = "rules_bound"
    RULES_MISSING = "rules_missing"
    RULES_STALE = "rules_stale"
    PRIOR_ART_BOUND = "prior_art_bound"
    PRIOR_ART_UNRESOLVED = "prior_art_unresolved"
    HUMAN_CONFIRMATIONS_OPEN = "human_confirmations_open"
    HUMAN_CONFIRMATIONS_COMPLETE = "human_confirmations_complete"
    ARTIFACT_FAMILIES_DISTINGUISHED = "artifact_families_distinguished"
    EXTERNAL_FILING_ONLY = "external_filing_only"
    NEVER_MARKED_SUBMITTED = "never_marked_submitted"
    NOT_LEGAL_ADVICE = "not_legal_advice"
    NO_CERTIFICATION_ASSERTED = "no_certification_asserted"
    APPROVAL_BOUND = "approval_bound"
    APPROVAL_INVALIDATED = "approval_invalidated"
    QUARANTINE = "quarantine"


class RulePackStatus(str, Enum):
    """Compact projection of filing-obligation pack status."""

    DRAFT = "draft"
    REVIEWED = "reviewed"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FilingPackageError(ValueError):
    """Base error for filing-package compiler failures."""

    def __init__(self, message: str, *, code: str = "filing_package_error") -> None:
        super().__init__(message)
        self.code = code

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)[:256]}


class ForbiddenPackageActionError(FilingPackageError):
    """Raised when a sign/pay/file/submit/certify action is attempted."""

    def __init__(self, action: str, message: str | None = None) -> None:
        action_s = str(action)
        super().__init__(
            message
            or (
                f"filing package forbids action {action_s!r}: filing remains "
                "external; this processor cannot sign, pay, file, certify, or "
                "claim Patent Center validation"
            ),
            code="forbidden_package_action",
        )
        self.action = action_s


class PackageNotValidatedError(FilingPackageError):
    """Raised when an operation requires a validated package."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="package_not_validated")


class PackageApprovalInvalidatedError(FilingPackageError):
    """Raised when material inputs no longer match a bound approval."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="package_approval_invalidated")


class PackageValidationBlockedError(FilingPackageError):
    """Raised when validate() is attempted while blocking reasons remain."""

    def __init__(
        self,
        message: str,
        *,
        block_reasons: Sequence[str] = (),
    ) -> None:
        super().__init__(message, code="package_validation_blocked")
        self.block_reasons = tuple(block_reasons)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _require_str(value: Any, field: str, *, max_len: int = 4096) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be str, got {type(value).__name__}")
    text = value.strip()
    if not text:
        raise ValueError(f"{field} must be non-empty")
    if len(text) > max_len:
        raise ValueError(f"{field} exceeds max length {max_len}")
    return text


def _optional_str(value: Any, field: str, *, max_len: int = 4096) -> str | None:
    if value is None:
        return None
    return _require_str(value, field, max_len=max_len)


def _identifier(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=256)
    if not _ID_RE.match(text):
        raise ValueError(f"{field} has invalid identifier shape")
    return text


def _optional_identifier(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _identifier(value, field)


def _sha256_hex_field(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64)
    lowered = text.lower()
    if not _SHA256_RE.match(lowered):
        raise ValueError(f"{field} must be a 64-char lowercase hex sha256")
    return lowered


def _optional_sha256(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _sha256_hex_field(value, field)


def _iso_utc(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64)
    if not _ISO_UTC_RE.match(text):
        raise ValueError(f"{field} must be ISO-8601 UTC timestamp")
    return text


def _optional_iso_utc(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _iso_utc(value, field)


def _coerce_enum(enum_cls: type[Enum], value: Any, field: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value)
        except ValueError as exc:
            raise ValueError(f"invalid {field}: {value!r}") from exc
    raise TypeError(f"{field} must be {enum_cls.__name__} or str")


def _coerce_classification(value: Any) -> DisclosureClassification:
    if isinstance(value, DisclosureClassification):
        return value
    if isinstance(value, str):
        try:
            return DisclosureClassification(value)
        except ValueError as exc:
            raise ValueError(f"invalid classification: {value!r}") from exc
    raise TypeError("classification must be DisclosureClassification or str")


def _tuple_of_str(
    value: Any, field: str, *, max_items: int = 256
) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raise TypeError(f"{field} must be a sequence of str, not str")
    if not isinstance(value, Sequence):
        raise TypeError(f"{field} must be a sequence of str")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    out: list[str] = []
    for i, item in enumerate(value):
        if not isinstance(item, str):
            raise TypeError(f"{field}[{i}] must be str")
        text = item.strip()
        if not text:
            raise ValueError(f"{field}[{i}] must be non-empty")
        if len(text) > 512:
            raise ValueError(f"{field}[{i}] exceeds max length 512")
        out.append(text)
    return tuple(out)


def _frozen_str_map(
    value: Any, field: str, *, max_items: int = 64
) -> Mapping[str, str]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    out: dict[str, str] = {}
    for k, v in value.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise TypeError(f"{field} keys and values must be str")
        ks, vs = k.strip(), v.strip()
        if not ks:
            raise ValueError(f"{field} key must be non-empty")
        out[ks] = vs
    return MappingProxyType(out)


def _default_id_factory() -> str:
    return uuid.uuid4().hex[:12]


def assert_action_allowed(action: str) -> None:
    """Fail closed if *action* is a forbidden package capability."""
    key = _require_str(action, "action", max_len=128).lower().replace(" ", "_")
    if key in FORBIDDEN_PACKAGE_ACTIONS:
        raise ForbiddenPackageActionError(key)
    if key.startswith(
        (
            "sign_",
            "pay_",
            "file_",
            "submit_",
            "mark_submitted",
            "mark_as_submitted",
            "fabricate_",
            "assert_certif",
            "claim_patent_center",
        )
    ):
        raise ForbiddenPackageActionError(key)
    for token in (
        "sign_and_file",
        "pay_and_file",
        "auto_file",
        "auto_submit",
        "fabricate_receipt",
        "select_legal_strategy",
        "assert_human_certification",
    ):
        if token in key:
            raise ForbiddenPackageActionError(key)


def is_forbidden_action(action: str) -> bool:
    try:
        assert_action_allowed(action)
    except ForbiddenPackageActionError:
        return True
    except (TypeError, ValueError):
        return True
    return False


# ---------------------------------------------------------------------------
# Component records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PackageFileEntry:
    """One original file or rendered derivative bound by content digest."""

    file_id: str
    family: PackageArtifactFamily | str
    role: OriginalFileRole | str
    media_kind: MediaKind | str
    content_digest: str
    filename: str
    source_root: str | None = None
    byte_size: int | None = None
    derived_from_file_id: str | None = None
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "file_id", _identifier(self.file_id, "file_id"))
        family = _coerce_enum(PackageArtifactFamily, self.family, "family")
        if family not in (
            PackageArtifactFamily.ORIGINAL_FILE,
            PackageArtifactFamily.RENDERED_DERIVATIVE,
        ):
            raise FilingPackageError(
                "PackageFileEntry.family must be original_file or "
                "rendered_derivative",
                code="invalid_file_family",
            )
        object.__setattr__(self, "family", family)
        object.__setattr__(
            self, "role", _coerce_enum(OriginalFileRole, self.role, "role")
        )
        object.__setattr__(
            self,
            "media_kind",
            _coerce_enum(MediaKind, self.media_kind, "media_kind"),
        )
        object.__setattr__(
            self,
            "content_digest",
            _sha256_hex_field(self.content_digest, "content_digest"),
        )
        object.__setattr__(
            self,
            "filename",
            _require_str(self.filename, "filename", max_len=512),
        )
        object.__setattr__(
            self,
            "source_root",
            _optional_str(self.source_root, "source_root", max_len=1024),
        )
        if self.byte_size is not None:
            if isinstance(self.byte_size, bool) or not isinstance(self.byte_size, int):
                raise TypeError("byte_size must be int or None")
            if self.byte_size < 0:
                raise ValueError("byte_size must be non-negative")
        object.__setattr__(
            self,
            "derived_from_file_id",
            _optional_identifier(self.derived_from_file_id, "derived_from_file_id"),
        )
        if (
            family is PackageArtifactFamily.RENDERED_DERIVATIVE
            and self.derived_from_file_id is None
        ):
            # Soft warning path is handled at package level; allow empty for
            # imported USPTO conversions whose parent is external.
            pass
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "byte_size": self.byte_size,
            "content_digest": self.content_digest,
            "derived_from_file_id": self.derived_from_file_id,
            "family": self.family.value
            if isinstance(self.family, PackageArtifactFamily)
            else str(self.family),
            "file_id": self.file_id,
            "filename": self.filename,
            "labels": dict(self.labels),
            "media_kind": self.media_kind.value
            if isinstance(self.media_kind, MediaKind)
            else str(self.media_kind),
            "role": self.role.value
            if isinstance(self.role, OriginalFileRole)
            else str(self.role),
            "source_root": self.source_root,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PackageFileEntry":
        if not isinstance(value, Mapping):
            raise TypeError("PackageFileEntry must be a mapping")
        return cls(
            file_id=value.get("file_id", ""),
            family=value.get("family", PackageArtifactFamily.ORIGINAL_FILE.value),
            role=value.get("role", OriginalFileRole.UNKNOWN.value),
            media_kind=value.get("media_kind", MediaKind.UNKNOWN.value),
            content_digest=value.get("content_digest", ""),
            filename=value.get("filename", ""),
            source_root=value.get("source_root"),
            byte_size=value.get("byte_size"),
            derived_from_file_id=value.get("derived_from_file_id"),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class ProposedAdsField:
    """A proposed Application Data Sheet field (proposed metadata only)."""

    field_id: str
    field_name: str
    proposed_value: str
    origin: str = "operator_supplied"
    required_confirmation: bool = True
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "field_id", _identifier(self.field_id, "field_id"))
        object.__setattr__(
            self,
            "field_name",
            _require_str(self.field_name, "field_name", max_len=256),
        )
        object.__setattr__(
            self,
            "proposed_value",
            _require_str(self.proposed_value, "proposed_value", max_len=4096),
        )
        object.__setattr__(
            self, "origin", _require_str(self.origin, "origin", max_len=128)
        )
        if not isinstance(self.required_confirmation, bool):
            raise TypeError("required_confirmation must be bool")
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_id": self.field_id,
            "field_name": self.field_name,
            "labels": dict(self.labels),
            "origin": self.origin,
            "proposed_value": self.proposed_value,
            "required_confirmation": self.required_confirmation,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProposedAdsField":
        if not isinstance(value, Mapping):
            raise TypeError("ProposedAdsField must be a mapping")
        return cls(
            field_id=value.get("field_id", ""),
            field_name=value.get("field_name", ""),
            proposed_value=value.get("proposed_value", ""),
            origin=value.get("origin", "operator_supplied"),
            required_confirmation=bool(value.get("required_confirmation", True)),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class DrawingsInventoryItem:
    """One sheet/figure inventory row (not a rendering)."""

    item_id: str
    figure_label: str
    sheet_number: int | None = None
    description: str | None = None
    content_digest: str | None = None
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "item_id", _identifier(self.item_id, "item_id"))
        object.__setattr__(
            self,
            "figure_label",
            _require_str(self.figure_label, "figure_label", max_len=128),
        )
        if self.sheet_number is not None:
            if isinstance(self.sheet_number, bool) or not isinstance(
                self.sheet_number, int
            ):
                raise TypeError("sheet_number must be int or None")
            if self.sheet_number < 0:
                raise ValueError("sheet_number must be non-negative")
        object.__setattr__(
            self,
            "description",
            _optional_str(self.description, "description", max_len=1024),
        )
        object.__setattr__(
            self,
            "content_digest",
            _optional_sha256(self.content_digest, "content_digest"),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_digest": self.content_digest,
            "description": self.description,
            "figure_label": self.figure_label,
            "item_id": self.item_id,
            "labels": dict(self.labels),
            "sheet_number": self.sheet_number,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DrawingsInventoryItem":
        if not isinstance(value, Mapping):
            raise TypeError("DrawingsInventoryItem must be a mapping")
        return cls(
            item_id=value.get("item_id", ""),
            figure_label=value.get("figure_label", ""),
            sheet_number=value.get("sheet_number"),
            description=value.get("description"),
            content_digest=value.get("content_digest"),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class OperatorChecklistItem:
    """Operator checklist row requiring (or recording) human confirmation."""

    item_id: str
    category: ChecklistCategory | str
    summary: str
    mandatory: bool = True
    requires_human_confirmation: bool = True
    confirmed: bool = False
    confirmed_by: str | None = None
    confirmed_at_utc: str | None = None
    bound_package_digest: str | None = None
    authority_citation: str | None = None
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "item_id", _identifier(self.item_id, "item_id"))
        object.__setattr__(
            self,
            "category",
            _coerce_enum(ChecklistCategory, self.category, "category"),
        )
        object.__setattr__(
            self, "summary", _require_str(self.summary, "summary", max_len=1024)
        )
        for flag_name in (
            "mandatory",
            "requires_human_confirmation",
            "confirmed",
        ):
            if not isinstance(getattr(self, flag_name), bool):
                raise TypeError(f"{flag_name} must be bool")
        object.__setattr__(
            self,
            "confirmed_by",
            _optional_str(self.confirmed_by, "confirmed_by", max_len=256),
        )
        object.__setattr__(
            self,
            "confirmed_at_utc",
            _optional_iso_utc(self.confirmed_at_utc, "confirmed_at_utc"),
        )
        object.__setattr__(
            self,
            "bound_package_digest",
            _optional_sha256(self.bound_package_digest, "bound_package_digest"),
        )
        object.__setattr__(
            self,
            "authority_citation",
            _optional_str(self.authority_citation, "authority_citation", max_len=256),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )
        if self.confirmed:
            if not self.confirmed_by or not self.confirmed_at_utc:
                raise FilingPackageError(
                    "confirmed checklist items require confirmed_by and "
                    "confirmed_at_utc",
                    code="incomplete_confirmation",
                )

    @property
    def is_open(self) -> bool:
        if not self.mandatory:
            return False
        if not self.requires_human_confirmation:
            return False
        return not self.confirmed

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_citation": self.authority_citation,
            "bound_package_digest": self.bound_package_digest,
            "category": self.category.value
            if isinstance(self.category, ChecklistCategory)
            else str(self.category),
            "confirmed": self.confirmed,
            "confirmed_at_utc": self.confirmed_at_utc,
            "confirmed_by": self.confirmed_by,
            "item_id": self.item_id,
            "labels": dict(self.labels),
            "mandatory": self.mandatory,
            "requires_human_confirmation": self.requires_human_confirmation,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OperatorChecklistItem":
        if not isinstance(value, Mapping):
            raise TypeError("OperatorChecklistItem must be a mapping")
        return cls(
            item_id=value.get("item_id", ""),
            category=value.get("category", ChecklistCategory.OTHER.value),
            summary=value.get("summary", ""),
            mandatory=bool(value.get("mandatory", True)),
            requires_human_confirmation=bool(
                value.get("requires_human_confirmation", True)
            ),
            confirmed=bool(value.get("confirmed", False)),
            confirmed_by=value.get("confirmed_by"),
            confirmed_at_utc=value.get("confirmed_at_utc"),
            bound_package_digest=value.get("bound_package_digest"),
            authority_citation=value.get("authority_citation"),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class RulePackBinding:
    """Binding to an approved filing-obligation pack (PATLAW-137 input)."""

    pack_id: str
    pack_version: str
    pack_digest: str
    status: RulePackStatus | str
    source_digests_recorded: bool
    human_approval_recorded: bool
    expected_pack_digest: str | None = None
    rule_ids: tuple[str, ...] = ()
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "pack_id", _identifier(self.pack_id, "pack_id"))
        object.__setattr__(
            self,
            "pack_version",
            _require_str(self.pack_version, "pack_version", max_len=64),
        )
        object.__setattr__(
            self,
            "pack_digest",
            _sha256_hex_field(self.pack_digest, "pack_digest"),
        )
        object.__setattr__(
            self, "status", _coerce_enum(RulePackStatus, self.status, "status")
        )
        if not isinstance(self.source_digests_recorded, bool):
            raise TypeError("source_digests_recorded must be bool")
        if not isinstance(self.human_approval_recorded, bool):
            raise TypeError("human_approval_recorded must be bool")
        object.__setattr__(
            self,
            "expected_pack_digest",
            _optional_sha256(self.expected_pack_digest, "expected_pack_digest"),
        )
        object.__setattr__(
            self, "rule_ids", _tuple_of_str(self.rule_ids, "rule_ids", max_items=512)
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )

    @property
    def is_active(self) -> bool:
        return self.status is RulePackStatus.ACTIVE

    @property
    def is_stale(self) -> bool:
        if self.expected_pack_digest is None:
            return False
        return self.pack_digest != self.expected_pack_digest

    def to_dict(self) -> dict[str, Any]:
        return {
            "expected_pack_digest": self.expected_pack_digest,
            "human_approval_recorded": self.human_approval_recorded,
            "labels": dict(self.labels),
            "pack_digest": self.pack_digest,
            "pack_id": self.pack_id,
            "pack_version": self.pack_version,
            "rule_ids": list(self.rule_ids),
            "source_digests_recorded": self.source_digests_recorded,
            "status": self.status.value
            if isinstance(self.status, RulePackStatus)
            else str(self.status),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RulePackBinding":
        if not isinstance(value, Mapping):
            raise TypeError("RulePackBinding must be a mapping")
        return cls(
            pack_id=value.get("pack_id", ""),
            pack_version=value.get("pack_version", ""),
            pack_digest=value.get("pack_digest", ""),
            status=value.get("status", RulePackStatus.UNKNOWN.value),
            source_digests_recorded=bool(value.get("source_digests_recorded", False)),
            human_approval_recorded=bool(value.get("human_approval_recorded", False)),
            expected_pack_digest=value.get("expected_pack_digest"),
            rule_ids=tuple(value.get("rule_ids") or ()),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class PriorArtCoverageBinding:
    """Binding to prior-art coverage signoff (PATLAW-151 input)."""

    declaration_id: str
    coverage_digest: str
    coverage_complete: bool
    human_signoff_recorded: bool
    unresolved_gap_ids: tuple[str, ...] = ()
    blocking_reason_codes: tuple[str, ...] = ()
    ids_queue_digest: str | None = None
    expected_coverage_digest: str | None = None
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "declaration_id",
            _identifier(self.declaration_id, "declaration_id"),
        )
        object.__setattr__(
            self,
            "coverage_digest",
            _sha256_hex_field(self.coverage_digest, "coverage_digest"),
        )
        if not isinstance(self.coverage_complete, bool):
            raise TypeError("coverage_complete must be bool")
        if not isinstance(self.human_signoff_recorded, bool):
            raise TypeError("human_signoff_recorded must be bool")
        object.__setattr__(
            self,
            "unresolved_gap_ids",
            _tuple_of_str(self.unresolved_gap_ids, "unresolved_gap_ids"),
        )
        object.__setattr__(
            self,
            "blocking_reason_codes",
            _tuple_of_str(self.blocking_reason_codes, "blocking_reason_codes"),
        )
        object.__setattr__(
            self,
            "ids_queue_digest",
            _optional_sha256(self.ids_queue_digest, "ids_queue_digest"),
        )
        object.__setattr__(
            self,
            "expected_coverage_digest",
            _optional_sha256(
                self.expected_coverage_digest, "expected_coverage_digest"
            ),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )

    @property
    def is_stale(self) -> bool:
        if self.expected_coverage_digest is None:
            return False
        return self.coverage_digest != self.expected_coverage_digest

    @property
    def is_resolved(self) -> bool:
        if self.is_stale:
            return False
        if not self.coverage_complete:
            return False
        if self.unresolved_gap_ids:
            return False
        if self.blocking_reason_codes:
            return False
        if not self.human_signoff_recorded:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocking_reason_codes": list(self.blocking_reason_codes),
            "coverage_complete": self.coverage_complete,
            "coverage_digest": self.coverage_digest,
            "declaration_id": self.declaration_id,
            "expected_coverage_digest": self.expected_coverage_digest,
            "human_signoff_recorded": self.human_signoff_recorded,
            "ids_queue_digest": self.ids_queue_digest,
            "labels": dict(self.labels),
            "unresolved_gap_ids": list(self.unresolved_gap_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PriorArtCoverageBinding":
        if not isinstance(value, Mapping):
            raise TypeError("PriorArtCoverageBinding must be a mapping")
        return cls(
            declaration_id=value.get("declaration_id", ""),
            coverage_digest=value.get("coverage_digest", ""),
            coverage_complete=bool(value.get("coverage_complete", False)),
            human_signoff_recorded=bool(value.get("human_signoff_recorded", False)),
            unresolved_gap_ids=tuple(value.get("unresolved_gap_ids") or ()),
            blocking_reason_codes=tuple(value.get("blocking_reason_codes") or ()),
            ids_queue_digest=value.get("ids_queue_digest"),
            expected_coverage_digest=value.get("expected_coverage_digest"),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class PackageApproval:
    """Named human approval bound to an exact package digest."""

    approval_id: str
    package_digest: str
    approver_name: str
    approved_at_utc: str
    statement: str
    output_kind: str = OUTPUT_KIND_PACKAGE_APPROVAL
    content_digest: str = ""
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "approval_id", _identifier(self.approval_id, "approval_id")
        )
        object.__setattr__(
            self,
            "package_digest",
            _sha256_hex_field(self.package_digest, "package_digest"),
        )
        object.__setattr__(
            self,
            "approver_name",
            _require_str(self.approver_name, "approver_name", max_len=256),
        )
        object.__setattr__(
            self,
            "approved_at_utc",
            _iso_utc(self.approved_at_utc, "approved_at_utc"),
        )
        object.__setattr__(
            self,
            "statement",
            _require_str(self.statement, "statement", max_len=4096),
        )
        object.__setattr__(
            self,
            "output_kind",
            _require_str(self.output_kind, "output_kind", max_len=128),
        )
        if self.output_kind != OUTPUT_KIND_PACKAGE_APPROVAL:
            raise FilingPackageError(
                f"output_kind must be {OUTPUT_KIND_PACKAGE_APPROVAL!r}",
                code="invalid_output_kind",
            )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )
        material = self.material_payload()
        digest = sha256_hex(canonical_json(material))
        if self.content_digest:
            existing = _sha256_hex_field(self.content_digest, "content_digest")
            if existing != digest:
                raise FilingPackageError(
                    "content_digest does not match approval material payload",
                    code="content_digest_mismatch",
                )
            object.__setattr__(self, "content_digest", existing)
        else:
            object.__setattr__(self, "content_digest", digest)

    def material_payload(self) -> dict[str, Any]:
        return {
            "approved_at_utc": self.approved_at_utc,
            "approver_name": self.approver_name,
            "labels": dict(self.labels),
            "output_kind": self.output_kind,
            "package_digest": self.package_digest,
            "statement": self.statement,
        }

    def binds_package_digest(self, package_digest: str) -> bool:
        return self.package_digest == _sha256_hex_field(
            package_digest, "package_digest"
        )

    def to_dict(self) -> dict[str, Any]:
        payload = self.material_payload()
        payload["approval_id"] = self.approval_id
        payload["content_digest"] = self.content_digest
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PackageApproval":
        if not isinstance(value, Mapping):
            raise TypeError("PackageApproval must be a mapping")
        return cls(
            approval_id=value.get("approval_id", ""),
            package_digest=value.get("package_digest", ""),
            approver_name=value.get("approver_name", ""),
            approved_at_utc=value.get("approved_at_utc", ""),
            statement=value.get("statement", ""),
            output_kind=value.get("output_kind", OUTPUT_KIND_PACKAGE_APPROVAL),
            content_digest=value.get("content_digest", ""),
            labels=value.get("labels") or {},
        )


# ---------------------------------------------------------------------------
# Package input / compiled manifest
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FilingPackageInput:
    """Immutable material inputs for package compilation."""

    matter_id: str
    application_type: str
    original_files: tuple[PackageFileEntry, ...]
    proposed_ads_fields: tuple[ProposedAdsField, ...]
    drawings_inventory: tuple[DrawingsInventoryItem, ...]
    operator_checklist: tuple[OperatorChecklistItem, ...]
    rule_pack: RulePackBinding | None
    prior_art: PriorArtCoverageBinding | None
    classification: DisclosureClassification | str = (
        DisclosureClassification.CONFIDENTIAL_APPLICATION
    )
    portfolio_fact_digest: str | None = None
    candidate_dates_digest: str | None = None
    source_roots: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    labels: Mapping[str, str] = MappingProxyType({})
    require_mandatory_checklist_categories: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "matter_id", _identifier(self.matter_id, "matter_id")
        )
        object.__setattr__(
            self,
            "application_type",
            _require_str(self.application_type, "application_type", max_len=64),
        )
        originals = _coerce_file_entries(
            self.original_files, "original_files", expected_family=None
        )
        if len(originals) > DEFAULT_MAX_FILES:
            raise FilingPackageError(
                f"original_files exceeds max {DEFAULT_MAX_FILES}",
                code="too_many_files",
            )
        object.__setattr__(self, "original_files", originals)

        ads = _coerce_ads_fields(self.proposed_ads_fields, "proposed_ads_fields")
        if len(ads) > DEFAULT_MAX_ADS_FIELDS:
            raise FilingPackageError(
                f"proposed_ads_fields exceeds max {DEFAULT_MAX_ADS_FIELDS}",
                code="too_many_ads_fields",
            )
        object.__setattr__(self, "proposed_ads_fields", ads)

        drawings = _coerce_drawings(self.drawings_inventory, "drawings_inventory")
        if len(drawings) > DEFAULT_MAX_DRAWINGS:
            raise FilingPackageError(
                f"drawings_inventory exceeds max {DEFAULT_MAX_DRAWINGS}",
                code="too_many_drawings",
            )
        object.__setattr__(self, "drawings_inventory", drawings)

        checklist = _coerce_checklist(self.operator_checklist, "operator_checklist")
        if len(checklist) > DEFAULT_MAX_CHECKLIST:
            raise FilingPackageError(
                f"operator_checklist exceeds max {DEFAULT_MAX_CHECKLIST}",
                code="too_many_checklist_items",
            )
        object.__setattr__(self, "operator_checklist", checklist)

        if self.rule_pack is not None and not isinstance(
            self.rule_pack, RulePackBinding
        ):
            if isinstance(self.rule_pack, Mapping):
                object.__setattr__(
                    self, "rule_pack", RulePackBinding.from_dict(self.rule_pack)
                )
            else:
                raise TypeError("rule_pack must be RulePackBinding or None")
        if self.prior_art is not None and not isinstance(
            self.prior_art, PriorArtCoverageBinding
        ):
            if isinstance(self.prior_art, Mapping):
                object.__setattr__(
                    self,
                    "prior_art",
                    PriorArtCoverageBinding.from_dict(self.prior_art),
                )
            else:
                raise TypeError("prior_art must be PriorArtCoverageBinding or None")

        object.__setattr__(
            self,
            "classification",
            _coerce_classification(self.classification),
        )
        object.__setattr__(
            self,
            "portfolio_fact_digest",
            _optional_sha256(self.portfolio_fact_digest, "portfolio_fact_digest"),
        )
        object.__setattr__(
            self,
            "candidate_dates_digest",
            _optional_sha256(self.candidate_dates_digest, "candidate_dates_digest"),
        )
        object.__setattr__(
            self,
            "source_roots",
            _tuple_of_str(
                self.source_roots, "source_roots", max_items=DEFAULT_MAX_SOURCE_ROOTS
            ),
        )
        object.__setattr__(
            self,
            "warnings",
            _tuple_of_str(self.warnings, "warnings", max_items=DEFAULT_MAX_WARNINGS),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )
        if not isinstance(self.require_mandatory_checklist_categories, bool):
            raise TypeError("require_mandatory_checklist_categories must be bool")

    def material_payload(self) -> dict[str, Any]:
        """Material fields that determine the package digest."""
        return {
            "application_type": self.application_type,
            "candidate_dates_digest": self.candidate_dates_digest,
            "classification": self.classification.value
            if isinstance(self.classification, DisclosureClassification)
            else str(self.classification),
            "drawings_inventory": [d.to_dict() for d in self.drawings_inventory],
            "labels": dict(self.labels),
            "matter_id": self.matter_id,
            "operator_checklist": [
                {
                    "authority_citation": c.authority_citation,
                    "category": c.category.value
                    if isinstance(c.category, ChecklistCategory)
                    else str(c.category),
                    "item_id": c.item_id,
                    "labels": dict(c.labels),
                    "mandatory": c.mandatory,
                    "requires_human_confirmation": c.requires_human_confirmation,
                    "summary": c.summary,
                    # Intentionally exclude confirmed* fields from material
                    # digest so confirmation records can bind *to* the digest
                    # without circular dependence. Confirmation state is still
                    # validated separately and appears in the full manifest.
                }
                for c in self.operator_checklist
            ],
            "original_files": [f.to_dict() for f in self.original_files],
            "portfolio_fact_digest": self.portfolio_fact_digest,
            "prior_art": None if self.prior_art is None else self.prior_art.to_dict(),
            "proposed_ads_fields": [a.to_dict() for a in self.proposed_ads_fields],
            "require_mandatory_checklist_categories": (
                self.require_mandatory_checklist_categories
            ),
            "rule_pack": None if self.rule_pack is None else self.rule_pack.to_dict(),
            "schema_version": FILING_PACKAGE_SCHEMA_VERSION,
            "source_roots": list(self.source_roots),
            "warnings": list(self.warnings),
        }

    def package_digest(self) -> str:
        return sha256_hex(canonical_json(self.material_payload()))

    def to_dict(self) -> dict[str, Any]:
        payload = self.material_payload()
        # Surface confirmation state for transport (not in material digest).
        payload["operator_checklist"] = [c.to_dict() for c in self.operator_checklist]
        payload["package_digest"] = self.package_digest()
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FilingPackageInput":
        if not isinstance(value, Mapping):
            raise TypeError("FilingPackageInput must be a mapping")
        return cls(
            matter_id=value.get("matter_id", ""),
            application_type=value.get("application_type", "utility"),
            original_files=tuple(value.get("original_files") or ()),
            proposed_ads_fields=tuple(value.get("proposed_ads_fields") or ()),
            drawings_inventory=tuple(value.get("drawings_inventory") or ()),
            operator_checklist=tuple(value.get("operator_checklist") or ()),
            rule_pack=value.get("rule_pack"),
            prior_art=value.get("prior_art"),
            classification=value.get(
                "classification",
                DisclosureClassification.CONFIDENTIAL_APPLICATION.value,
            ),
            portfolio_fact_digest=value.get("portfolio_fact_digest"),
            candidate_dates_digest=value.get("candidate_dates_digest"),
            source_roots=tuple(value.get("source_roots") or ()),
            warnings=tuple(value.get("warnings") or ()),
            labels=value.get("labels") or {},
            require_mandatory_checklist_categories=bool(
                value.get("require_mandatory_checklist_categories", True)
            ),
        )


def _coerce_file_entries(
    value: Any,
    field: str,
    *,
    expected_family: PackageArtifactFamily | None,
) -> tuple[PackageFileEntry, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence")
    out: list[PackageFileEntry] = []
    for i, item in enumerate(value):
        if isinstance(item, PackageFileEntry):
            entry = item
        elif isinstance(item, Mapping):
            entry = PackageFileEntry.from_dict(item)
        else:
            raise TypeError(f"{field}[{i}] must be PackageFileEntry or mapping")
        if expected_family is not None and entry.family is not expected_family:
            raise FilingPackageError(
                f"{field}[{i}].family must be {expected_family.value}",
                code="file_family_mismatch",
            )
        out.append(entry)
    return tuple(out)


def _coerce_ads_fields(
    value: Any, field: str
) -> tuple[ProposedAdsField, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence")
    out: list[ProposedAdsField] = []
    for i, item in enumerate(value):
        if isinstance(item, ProposedAdsField):
            out.append(item)
        elif isinstance(item, Mapping):
            out.append(ProposedAdsField.from_dict(item))
        else:
            raise TypeError(f"{field}[{i}] must be ProposedAdsField or mapping")
    return tuple(out)


def _coerce_drawings(
    value: Any, field: str
) -> tuple[DrawingsInventoryItem, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence")
    out: list[DrawingsInventoryItem] = []
    for i, item in enumerate(value):
        if isinstance(item, DrawingsInventoryItem):
            out.append(item)
        elif isinstance(item, Mapping):
            out.append(DrawingsInventoryItem.from_dict(item))
        else:
            raise TypeError(f"{field}[{i}] must be DrawingsInventoryItem or mapping")
    return tuple(out)


def _coerce_checklist(
    value: Any, field: str
) -> tuple[OperatorChecklistItem, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence")
    out: list[OperatorChecklistItem] = []
    for i, item in enumerate(value):
        if isinstance(item, OperatorChecklistItem):
            out.append(item)
        elif isinstance(item, Mapping):
            out.append(OperatorChecklistItem.from_dict(item))
        else:
            raise TypeError(f"{field}[{i}] must be OperatorChecklistItem or mapping")
    return tuple(out)


@dataclass(frozen=True, slots=True)
class FilingPackageManifest:
    """Compiled content-addressed filing package with distinguished families.

    Capability locks: never submitted, never authorized to sign/pay/file.
    """

    schema_version: str
    package_id: str
    matter_id: str
    state: FilingPackageState | str
    package_digest: str
    application_type: str
    proposed_metadata: Mapping[str, Any]
    original_files: tuple[PackageFileEntry, ...]
    rendered_derivatives: tuple[PackageFileEntry, ...]
    operator_checklist: tuple[OperatorChecklistItem, ...]
    drawings_inventory: tuple[DrawingsInventoryItem, ...]
    rule_pack: RulePackBinding | None
    prior_art: PriorArtCoverageBinding | None
    block_reasons: tuple[str, ...]
    open_confirmation_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    source_roots: tuple[str, ...]
    classification: DisclosureClassification | str
    review_state: ReviewState | str
    output_kind: str = OUTPUT_KIND_FILING_PACKAGE
    disclaimer: str = FILING_PACKAGE_DISCLAIMER
    ruleset_version: str = FILING_PACKAGE_RULESET_VERSION
    content_digest: str = ""
    portfolio_fact_digest: str | None = None
    candidate_dates_digest: str | None = None
    approval: PackageApproval | None = None
    is_submitted: bool = False
    filing_is_external: bool = True
    can_sign: bool = False
    can_pay: bool = False
    can_file: bool = False
    certification_asserted: bool = False
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != FILING_PACKAGE_SCHEMA_VERSION:
            raise FilingPackageError(
                f"schema_version must be {FILING_PACKAGE_SCHEMA_VERSION}",
                code="schema_version_mismatch",
            )
        object.__setattr__(
            self, "package_id", _identifier(self.package_id, "package_id")
        )
        object.__setattr__(
            self, "matter_id", _identifier(self.matter_id, "matter_id")
        )
        object.__setattr__(
            self, "state", _coerce_enum(FilingPackageState, self.state, "state")
        )
        object.__setattr__(
            self,
            "package_digest",
            _sha256_hex_field(self.package_digest, "package_digest"),
        )
        object.__setattr__(
            self,
            "application_type",
            _require_str(self.application_type, "application_type", max_len=64),
        )
        if not isinstance(self.proposed_metadata, Mapping):
            raise TypeError("proposed_metadata must be a mapping")
        object.__setattr__(
            self,
            "proposed_metadata",
            MappingProxyType(dict(self.proposed_metadata)),
        )
        object.__setattr__(
            self,
            "original_files",
            _coerce_file_entries(
                self.original_files,
                "original_files",
                expected_family=PackageArtifactFamily.ORIGINAL_FILE,
            ),
        )
        object.__setattr__(
            self,
            "rendered_derivatives",
            _coerce_file_entries(
                self.rendered_derivatives,
                "rendered_derivatives",
                expected_family=PackageArtifactFamily.RENDERED_DERIVATIVE,
            ),
        )
        object.__setattr__(
            self,
            "operator_checklist",
            _coerce_checklist(self.operator_checklist, "operator_checklist"),
        )
        object.__setattr__(
            self,
            "drawings_inventory",
            _coerce_drawings(self.drawings_inventory, "drawings_inventory"),
        )
        if self.rule_pack is not None and not isinstance(
            self.rule_pack, RulePackBinding
        ):
            if isinstance(self.rule_pack, Mapping):
                object.__setattr__(
                    self, "rule_pack", RulePackBinding.from_dict(self.rule_pack)
                )
            else:
                raise TypeError("rule_pack must be RulePackBinding or None")
        if self.prior_art is not None and not isinstance(
            self.prior_art, PriorArtCoverageBinding
        ):
            if isinstance(self.prior_art, Mapping):
                object.__setattr__(
                    self,
                    "prior_art",
                    PriorArtCoverageBinding.from_dict(self.prior_art),
                )
            else:
                raise TypeError("prior_art must be PriorArtCoverageBinding or None")
        object.__setattr__(
            self,
            "block_reasons",
            _tuple_of_str(
                self.block_reasons, "block_reasons", max_items=DEFAULT_MAX_BLOCK_REASONS
            ),
        )
        object.__setattr__(
            self,
            "open_confirmation_ids",
            _tuple_of_str(self.open_confirmation_ids, "open_confirmation_ids"),
        )
        object.__setattr__(
            self,
            "reason_codes",
            _tuple_of_str(
                self.reason_codes, "reason_codes", max_items=DEFAULT_MAX_REASON_CODES
            ),
        )
        object.__setattr__(
            self,
            "warnings",
            _tuple_of_str(self.warnings, "warnings", max_items=DEFAULT_MAX_WARNINGS),
        )
        object.__setattr__(
            self,
            "source_roots",
            _tuple_of_str(
                self.source_roots, "source_roots", max_items=DEFAULT_MAX_SOURCE_ROOTS
            ),
        )
        object.__setattr__(
            self,
            "classification",
            _coerce_classification(self.classification),
        )
        object.__setattr__(
            self,
            "review_state",
            _coerce_enum(ReviewState, self.review_state, "review_state"),
        )
        object.__setattr__(
            self,
            "output_kind",
            _require_str(self.output_kind, "output_kind", max_len=128),
        )
        if self.output_kind != OUTPUT_KIND_FILING_PACKAGE:
            raise FilingPackageError(
                f"output_kind must be {OUTPUT_KIND_FILING_PACKAGE!r}",
                code="invalid_output_kind",
            )
        object.__setattr__(
            self,
            "disclaimer",
            _require_str(self.disclaimer, "disclaimer", max_len=4096),
        )
        object.__setattr__(
            self,
            "ruleset_version",
            _require_str(self.ruleset_version, "ruleset_version", max_len=128),
        )
        object.__setattr__(
            self,
            "portfolio_fact_digest",
            _optional_sha256(self.portfolio_fact_digest, "portfolio_fact_digest"),
        )
        object.__setattr__(
            self,
            "candidate_dates_digest",
            _optional_sha256(self.candidate_dates_digest, "candidate_dates_digest"),
        )
        if self.approval is not None and not isinstance(self.approval, PackageApproval):
            if isinstance(self.approval, Mapping):
                object.__setattr__(
                    self, "approval", PackageApproval.from_dict(self.approval)
                )
            else:
                raise TypeError("approval must be PackageApproval or None")
        # Capability locks — never elevatable.
        object.__setattr__(self, "is_submitted", False)
        object.__setattr__(self, "filing_is_external", True)
        object.__setattr__(self, "can_sign", False)
        object.__setattr__(self, "can_pay", False)
        object.__setattr__(self, "can_file", False)
        object.__setattr__(self, "certification_asserted", False)
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )

        # Validated state is fail-closed.
        state = self.state
        if state is FilingPackageState.VALIDATED and self.block_reasons:
            raise FilingPackageError(
                "validated state cannot retain block_reasons",
                code="validated_with_blocks",
            )
        if state is FilingPackageState.VALIDATED and self.open_confirmation_ids:
            raise FilingPackageError(
                "validated state cannot retain open confirmations",
                code="validated_with_open_confirmations",
            )

        material = self.material_payload()
        digest = sha256_hex(canonical_json(material))
        if self.content_digest:
            existing = _sha256_hex_field(self.content_digest, "content_digest")
            if existing != digest:
                raise FilingPackageError(
                    "content_digest does not match material payload",
                    code="content_digest_mismatch",
                )
            object.__setattr__(self, "content_digest", existing)
        else:
            object.__setattr__(self, "content_digest", digest)

    def material_payload(self) -> dict[str, Any]:
        return {
            "application_type": self.application_type,
            "block_reasons": list(self.block_reasons),
            "can_file": False,
            "can_pay": False,
            "can_sign": False,
            "candidate_dates_digest": self.candidate_dates_digest,
            "certification_asserted": False,
            "classification": self.classification.value
            if isinstance(self.classification, DisclosureClassification)
            else str(self.classification),
            "disclaimer": self.disclaimer,
            "drawings_inventory": [d.to_dict() for d in self.drawings_inventory],
            "filing_is_external": True,
            "is_submitted": False,
            "labels": dict(self.labels),
            "matter_id": self.matter_id,
            "open_confirmation_ids": list(self.open_confirmation_ids),
            "operator_checklist": [c.to_dict() for c in self.operator_checklist],
            "original_files": [f.to_dict() for f in self.original_files],
            "output_kind": self.output_kind,
            "package_digest": self.package_digest,
            "portfolio_fact_digest": self.portfolio_fact_digest,
            "prior_art": None if self.prior_art is None else self.prior_art.to_dict(),
            "proposed_metadata": dict(self.proposed_metadata),
            "reason_codes": list(self.reason_codes),
            "rendered_derivatives": [f.to_dict() for f in self.rendered_derivatives],
            "review_state": self.review_state.value
            if isinstance(self.review_state, ReviewState)
            else str(self.review_state),
            "rule_pack": None if self.rule_pack is None else self.rule_pack.to_dict(),
            "ruleset_version": self.ruleset_version,
            "schema_version": self.schema_version,
            "source_roots": list(self.source_roots),
            "state": self.state.value
            if isinstance(self.state, FilingPackageState)
            else str(self.state),
            "warnings": list(self.warnings),
        }

    @property
    def is_validated(self) -> bool:
        return self.state is FilingPackageState.VALIDATED

    @property
    def is_blocked(self) -> bool:
        return bool(self.block_reasons)

    def distinguished_families(self) -> Mapping[str, Any]:
        """Return the four distinguished output families explicitly."""
        return MappingProxyType(
            {
                PackageArtifactFamily.PROPOSED_METADATA.value: dict(
                    self.proposed_metadata
                ),
                PackageArtifactFamily.ORIGINAL_FILE.value: [
                    f.to_dict() for f in self.original_files
                ],
                PackageArtifactFamily.RENDERED_DERIVATIVE.value: [
                    f.to_dict() for f in self.rendered_derivatives
                ],
                PackageArtifactFamily.OPERATOR_CHECKLIST.value: [
                    c.to_dict() for c in self.operator_checklist
                ],
            }
        )

    def to_dict(self) -> dict[str, Any]:
        payload = self.material_payload()
        payload["content_digest"] = self.content_digest
        payload["package_id"] = self.package_id
        payload["approval"] = None if self.approval is None else self.approval.to_dict()
        # Explicit top-level keys for acceptance / golden consumers.
        payload["proposed_metadata"] = dict(self.proposed_metadata)
        payload["original_files"] = [f.to_dict() for f in self.original_files]
        payload["rendered_derivatives"] = [
            f.to_dict() for f in self.rendered_derivatives
        ]
        payload["operator_checklist"] = [c.to_dict() for c in self.operator_checklist]
        return payload

    def public_projection(self) -> dict[str, Any]:
        """Capability-free public surface (no private content)."""
        return {
            "application_type": self.application_type,
            "block_reasons": list(self.block_reasons),
            "can_file": False,
            "can_pay": False,
            "can_sign": False,
            "certification_asserted": False,
            "classification": self.classification.value
            if isinstance(self.classification, DisclosureClassification)
            else str(self.classification),
            "content_digest": self.content_digest,
            "disclaimer": self.disclaimer,
            "filing_is_external": True,
            "is_submitted": False,
            "matter_id": self.matter_id,
            "open_confirmation_ids": list(self.open_confirmation_ids),
            "output_kind": self.output_kind,
            "package_digest": self.package_digest,
            "package_id": self.package_id,
            "reason_codes": list(self.reason_codes),
            "review_state": self.review_state.value
            if isinstance(self.review_state, ReviewState)
            else str(self.review_state),
            "schema_version": self.schema_version,
            "state": self.state.value
            if isinstance(self.state, FilingPackageState)
            else str(self.state),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FilingPackageManifest":
        if not isinstance(value, Mapping):
            raise TypeError("FilingPackageManifest must be a mapping")
        return cls(
            schema_version=value.get(
                "schema_version", FILING_PACKAGE_SCHEMA_VERSION
            ),
            package_id=value.get("package_id", ""),
            matter_id=value.get("matter_id", ""),
            state=value.get("state", FilingPackageState.DRAFT.value),
            package_digest=value.get("package_digest", ""),
            application_type=value.get("application_type", "utility"),
            proposed_metadata=value.get("proposed_metadata") or {},
            original_files=tuple(value.get("original_files") or ()),
            rendered_derivatives=tuple(value.get("rendered_derivatives") or ()),
            operator_checklist=tuple(value.get("operator_checklist") or ()),
            drawings_inventory=tuple(value.get("drawings_inventory") or ()),
            rule_pack=value.get("rule_pack"),
            prior_art=value.get("prior_art"),
            block_reasons=tuple(value.get("block_reasons") or ()),
            open_confirmation_ids=tuple(value.get("open_confirmation_ids") or ()),
            reason_codes=tuple(value.get("reason_codes") or ()),
            warnings=tuple(value.get("warnings") or ()),
            source_roots=tuple(value.get("source_roots") or ()),
            classification=value.get(
                "classification",
                DisclosureClassification.CONFIDENTIAL_APPLICATION.value,
            ),
            review_state=value.get("review_state", ReviewState.REQUIRED.value),
            output_kind=value.get("output_kind", OUTPUT_KIND_FILING_PACKAGE),
            disclaimer=value.get("disclaimer", FILING_PACKAGE_DISCLAIMER),
            ruleset_version=value.get(
                "ruleset_version", FILING_PACKAGE_RULESET_VERSION
            ),
            content_digest=value.get("content_digest", ""),
            portfolio_fact_digest=value.get("portfolio_fact_digest"),
            candidate_dates_digest=value.get("candidate_dates_digest"),
            approval=value.get("approval"),
            is_submitted=False,
            filing_is_external=True,
            can_sign=False,
            can_pay=False,
            can_file=False,
            certification_asserted=False,
            labels=value.get("labels") or {},
        )


# ---------------------------------------------------------------------------
# Validation evaluation
# ---------------------------------------------------------------------------


def evaluate_validation_blocks(
    package_input: FilingPackageInput,
    *,
    package_digest: str | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Return (block_reasons, open_confirmation_ids, reason_codes).

    Fail-closed: any material gate failure produces a block reason.
    """
    if not isinstance(package_input, FilingPackageInput):
        raise TypeError("package_input must be FilingPackageInput")

    digest = package_digest or package_input.package_digest()
    blocks: list[str] = []
    reasons: list[str] = [
        FilingPackageReasonCode.MATERIAL_DIGEST_COMPUTED.value,
        FilingPackageReasonCode.ARTIFACT_FAMILIES_DISTINGUISHED.value,
        FilingPackageReasonCode.EXTERNAL_FILING_ONLY.value,
        FilingPackageReasonCode.NEVER_MARKED_SUBMITTED.value,
        FilingPackageReasonCode.NOT_LEGAL_ADVICE.value,
        FilingPackageReasonCode.NO_CERTIFICATION_ASSERTED.value,
    ]
    open_ids: list[str] = []

    # Quarantine
    if requires_quarantine(package_input.classification):
        blocks.append(ValidationBlockReason.QUARANTINE_BLOCK.value)
        reasons.append(FilingPackageReasonCode.QUARANTINE.value)

    # Original files required
    originals = [
        f
        for f in package_input.original_files
        if f.family is PackageArtifactFamily.ORIGINAL_FILE
    ]
    if not originals:
        blocks.append(ValidationBlockReason.MISSING_ORIGINAL_FILES.value)
        if not package_input.original_files:
            blocks.append(ValidationBlockReason.EMPTY_PACKAGE.value)

    # Rule pack
    pack = package_input.rule_pack
    if pack is None:
        blocks.append(ValidationBlockReason.MISSING_MANDATORY_RULES.value)
        reasons.append(FilingPackageReasonCode.RULES_MISSING.value)
    else:
        reasons.append(FilingPackageReasonCode.RULES_BOUND.value)
        if not pack.is_active:
            blocks.append(ValidationBlockReason.RULE_PACK_NOT_ACTIVE.value)
            blocks.append(ValidationBlockReason.MISSING_MANDATORY_RULES.value)
            reasons.append(FilingPackageReasonCode.RULES_MISSING.value)
        if not pack.source_digests_recorded or not pack.human_approval_recorded:
            blocks.append(ValidationBlockReason.MISSING_MANDATORY_RULES.value)
            reasons.append(FilingPackageReasonCode.RULES_MISSING.value)
        if pack.is_stale:
            blocks.append(ValidationBlockReason.STALE_MANDATORY_RULES.value)
            blocks.append(ValidationBlockReason.DIGEST_MISMATCH.value)
            reasons.append(FilingPackageReasonCode.RULES_STALE.value)
        if pack.status is RulePackStatus.SUPERSEDED:
            blocks.append(ValidationBlockReason.STALE_MANDATORY_RULES.value)
            reasons.append(FilingPackageReasonCode.RULES_STALE.value)

    # Prior art
    prior = package_input.prior_art
    if prior is None:
        blocks.append(ValidationBlockReason.UNRESOLVED_PRIOR_ART.value)
        blocks.append(ValidationBlockReason.PRIOR_ART_SIGNOFF_MISSING.value)
        reasons.append(FilingPackageReasonCode.PRIOR_ART_UNRESOLVED.value)
    else:
        reasons.append(FilingPackageReasonCode.PRIOR_ART_BOUND.value)
        if prior.is_stale:
            blocks.append(ValidationBlockReason.DIGEST_MISMATCH.value)
            blocks.append(ValidationBlockReason.UNRESOLVED_PRIOR_ART.value)
            reasons.append(FilingPackageReasonCode.PRIOR_ART_UNRESOLVED.value)
        if not prior.is_resolved:
            blocks.append(ValidationBlockReason.UNRESOLVED_PRIOR_ART.value)
            reasons.append(FilingPackageReasonCode.PRIOR_ART_UNRESOLVED.value)
            if not prior.human_signoff_recorded:
                blocks.append(ValidationBlockReason.PRIOR_ART_SIGNOFF_MISSING.value)
            if not prior.coverage_complete or prior.unresolved_gap_ids:
                blocks.append(ValidationBlockReason.UNRESOLVED_PRIOR_ART.value)

    # Mandatory checklist categories
    if package_input.require_mandatory_checklist_categories:
        present = {
            c.category.value
            if isinstance(c.category, ChecklistCategory)
            else str(c.category)
            for c in package_input.operator_checklist
        }
        missing = sorted(MANDATORY_CHECKLIST_CATEGORIES - present)
        if missing:
            blocks.append(ValidationBlockReason.MISSING_CHECKLIST_CATEGORIES.value)

    # Human confirmations on checklist
    for item in package_input.operator_checklist:
        if item.is_open:
            open_ids.append(item.item_id)
            continue
        if (
            item.confirmed
            and item.requires_human_confirmation
            and item.bound_package_digest is not None
            and item.bound_package_digest != digest
        ):
            blocks.append(ValidationBlockReason.DIGEST_MISMATCH.value)
            blocks.append(ValidationBlockReason.APPROVAL_DIGEST_MISMATCH.value)
            open_ids.append(item.item_id)

    if open_ids:
        blocks.append(ValidationBlockReason.HUMAN_CONFIRMATION_REQUIRED.value)
        reasons.append(FilingPackageReasonCode.HUMAN_CONFIRMATIONS_OPEN.value)
    else:
        # Only mark complete if there is at least one mandatory confirmation item
        mandatory_items = [
            i
            for i in package_input.operator_checklist
            if i.mandatory and i.requires_human_confirmation
        ]
        if mandatory_items:
            reasons.append(
                FilingPackageReasonCode.HUMAN_CONFIRMATIONS_COMPLETE.value
            )

    # Deduplicate preserving order
    def _dedupe(items: list[str]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(items))

    return _dedupe(blocks), _dedupe(open_ids), _dedupe(reasons)


def package_inputs_match(
    manifest: FilingPackageManifest, package_input: FilingPackageInput
) -> bool:
    """True when *package_input* still produces *manifest.package_digest*."""
    return manifest.package_digest == package_input.package_digest()


def default_mandatory_checklist(
    *,
    confirmed: bool = False,
    confirmed_by: str | None = None,
    confirmed_at_utc: str | None = None,
    bound_package_digest: str | None = None,
) -> tuple[OperatorChecklistItem, ...]:
    """Compact default operator checklist covering mandatory categories."""
    specs: tuple[tuple[str, ChecklistCategory, str, str | None], ...] = (
        (
            "check:forms",
            ChecklistCategory.FORMS,
            "Confirm required USPTO forms are selected and complete for review",
            "37 CFR 1.51",
        ),
        (
            "check:fees",
            ChecklistCategory.FEES,
            "Confirm fee codes/entity status; payment remains a natural-person action",
            "37 CFR 1.16",
        ),
        (
            "check:priority",
            ChecklistCategory.PRIORITY,
            "Review priority / benefit claims for accuracy and supporting documents",
            "35 U.S.C. 119/120",
        ),
        (
            "check:inventorship",
            ChecklistCategory.INVENTORSHIP,
            "Review inventorship listing and oath/declaration readiness",
            "35 U.S.C. 115",
        ),
        (
            "check:new-matter",
            ChecklistCategory.NEW_MATTER,
            "Confirm no new matter introduced relative to priority / parent filings",
            "35 U.S.C. 132",
        ),
        (
            "check:nonpublication",
            ChecklistCategory.NONPUBLICATION,
            "Review nonpublication request applicability and certifications",
            "35 U.S.C. 122(b)",
        ),
        (
            "check:export",
            ChecklistCategory.EXPORT_CONTROL,
            "Review export-control / foreign-filing-license considerations",
            "35 U.S.C. 184",
        ),
        (
            "check:ids",
            ChecklistCategory.IDS,
            "Review IDS queue and prior-art coverage signoff before handoff",
            "37 CFR 1.56/1.97",
        ),
    )
    items: list[OperatorChecklistItem] = []
    for item_id, category, summary, citation in specs:
        items.append(
            OperatorChecklistItem(
                item_id=item_id,
                category=category,
                summary=summary,
                mandatory=True,
                requires_human_confirmation=True,
                confirmed=confirmed,
                confirmed_by=confirmed_by if confirmed else None,
                confirmed_at_utc=confirmed_at_utc if confirmed else None,
                bound_package_digest=bound_package_digest if confirmed else None,
                authority_citation=citation,
            )
        )
    return tuple(items)


def confirm_checklist_items(
    package_input: FilingPackageInput,
    *,
    item_ids: Sequence[str] | None = None,
    confirmed_by: str,
    confirmed_at_utc: str,
    package_digest: str | None = None,
) -> FilingPackageInput:
    """Return a new input with selected checklist items confirmed.

    Confirmations bind to the material package digest (computed before
    confirmation state is applied).
    """
    digest = package_digest or package_input.package_digest()
    target = set(item_ids) if item_ids is not None else None
    updated: list[OperatorChecklistItem] = []
    for item in package_input.operator_checklist:
        if target is not None and item.item_id not in target:
            updated.append(item)
            continue
        if not item.requires_human_confirmation:
            updated.append(item)
            continue
        updated.append(
            OperatorChecklistItem(
                item_id=item.item_id,
                category=item.category,
                summary=item.summary,
                mandatory=item.mandatory,
                requires_human_confirmation=item.requires_human_confirmation,
                confirmed=True,
                confirmed_by=confirmed_by,
                confirmed_at_utc=confirmed_at_utc,
                bound_package_digest=digest,
                authority_citation=item.authority_citation,
                labels=dict(item.labels),
            )
        )
    data = package_input.to_dict()
    data.pop("package_digest", None)
    data["operator_checklist"] = [c.to_dict() for c in updated]
    return FilingPackageInput.from_dict(data)


# ---------------------------------------------------------------------------
# Compiler
# ---------------------------------------------------------------------------


class FilingPackageCompiler:
    """Compile and validate rule- and prior-art-aware filing packages.

    Never signs, pays, files, or asserts human certifications.
    """

    def __init__(
        self,
        *,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._id_factory = id_factory or _default_id_factory

    def perform_action(self, action: str) -> None:
        assert_action_allowed(action)
        raise FilingPackageError(
            f"action {action!r} is not implemented by FilingPackageCompiler",
            code="action_not_implemented",
        )

    def sign(self) -> None:
        raise ForbiddenPackageActionError("sign")

    def pay(self) -> None:
        raise ForbiddenPackageActionError("pay")

    def file(self) -> None:
        raise ForbiddenPackageActionError("file")

    def submit(self) -> None:
        raise ForbiddenPackageActionError("submit")

    def mark_submitted(self) -> None:
        raise ForbiddenPackageActionError("mark_submitted")

    def assert_human_certification(self) -> None:
        raise ForbiddenPackageActionError("assert_human_certification")

    def claim_patent_center_validation(self) -> None:
        raise ForbiddenPackageActionError("claim_patent_center_validation")

    def compile(
        self,
        package_input: FilingPackageInput,
        *,
        package_id: str | None = None,
        force_state: FilingPackageState | str | None = None,
    ) -> FilingPackageManifest:
        """Compile a draft (or explicitly forced) package from material inputs."""
        if not isinstance(package_input, FilingPackageInput):
            raise TypeError("package_input must be FilingPackageInput")

        package_digest = package_input.package_digest()
        blocks, open_ids, reasons = evaluate_validation_blocks(
            package_input, package_digest=package_digest
        )

        originals = tuple(
            f
            for f in package_input.original_files
            if f.family is PackageArtifactFamily.ORIGINAL_FILE
        )
        derivatives = tuple(
            f
            for f in package_input.original_files
            if f.family is PackageArtifactFamily.RENDERED_DERIVATIVE
        )
        # Also accept derivatives mixed into original_files list for convenience;
        # callers may also pass only originals and set derivatives via a separate
        # list — FilingPackageInput stores all files under original_files and we
        # split by family here.

        proposed_metadata = {
            "family": PackageArtifactFamily.PROPOSED_METADATA.value,
            "ads_fields": [a.to_dict() for a in package_input.proposed_ads_fields],
            "note": (
                "Proposed metadata only — not filed fact and not a USPTO "
                "record until a human submits via Patent Center."
            ),
        }

        if force_state is not None:
            state = _coerce_enum(FilingPackageState, force_state, "force_state")
            if state is FilingPackageState.VALIDATED and blocks:
                raise PackageValidationBlockedError(
                    "cannot force validated state while block reasons remain",
                    block_reasons=blocks,
                )
        else:
            state = FilingPackageState.DRAFT

        reasons_list = list(reasons)
        if state is FilingPackageState.DRAFT:
            reasons_list.append(FilingPackageReasonCode.PACKAGE_DRAFT.value)
        reasons_list.append(FilingPackageReasonCode.PACKAGE_COMPILED.value)
        reasons_list = list(dict.fromkeys(reasons_list))

        review_state = (
            ReviewState.REQUIRED
            if blocks or open_ids
            else ReviewState.COMPLETE
        )

        # Privacy: private classification stays private; quarantine already blocked.
        classification = package_input.classification
        if is_private_classification(classification):
            # No public sink emission from this compiler.
            pass

        pid = package_id or f"pkg:{self._id_factory()}"
        return FilingPackageManifest(
            schema_version=FILING_PACKAGE_SCHEMA_VERSION,
            package_id=pid,
            matter_id=package_input.matter_id,
            state=state,
            package_digest=package_digest,
            application_type=package_input.application_type,
            proposed_metadata=proposed_metadata,
            original_files=originals,
            rendered_derivatives=derivatives,
            operator_checklist=package_input.operator_checklist,
            drawings_inventory=package_input.drawings_inventory,
            rule_pack=package_input.rule_pack,
            prior_art=package_input.prior_art,
            block_reasons=blocks,
            open_confirmation_ids=open_ids,
            reason_codes=tuple(reasons_list),
            warnings=package_input.warnings,
            source_roots=package_input.source_roots,
            classification=classification,
            review_state=review_state,
            portfolio_fact_digest=package_input.portfolio_fact_digest,
            candidate_dates_digest=package_input.candidate_dates_digest,
            labels=dict(package_input.labels),
        )

    def validate(
        self,
        package_input: FilingPackageInput,
        *,
        package_id: str | None = None,
        raise_if_blocked: bool = False,
    ) -> FilingPackageManifest:
        """Compile and advance to ``validated`` only when all gates pass."""
        draft = self.compile(package_input, package_id=package_id)
        if draft.block_reasons or draft.open_confirmation_ids:
            if raise_if_blocked:
                raise PackageValidationBlockedError(
                    "package validation blocked: "
                    + ", ".join(draft.block_reasons or draft.open_confirmation_ids),
                    block_reasons=draft.block_reasons,
                )
            return draft  # remains draft with blocks

        reasons = list(draft.reason_codes)
        reasons.append(FilingPackageReasonCode.PACKAGE_VALIDATED.value)
        reasons = list(dict.fromkeys(reasons))

        return FilingPackageManifest(
            schema_version=draft.schema_version,
            package_id=draft.package_id,
            matter_id=draft.matter_id,
            state=FilingPackageState.VALIDATED,
            package_digest=draft.package_digest,
            application_type=draft.application_type,
            proposed_metadata=dict(draft.proposed_metadata),
            original_files=draft.original_files,
            rendered_derivatives=draft.rendered_derivatives,
            operator_checklist=draft.operator_checklist,
            drawings_inventory=draft.drawings_inventory,
            rule_pack=draft.rule_pack,
            prior_art=draft.prior_art,
            block_reasons=(),
            open_confirmation_ids=(),
            reason_codes=tuple(reasons),
            warnings=draft.warnings,
            source_roots=draft.source_roots,
            classification=draft.classification,
            review_state=ReviewState.COMPLETE,
            portfolio_fact_digest=draft.portfolio_fact_digest,
            candidate_dates_digest=draft.candidate_dates_digest,
            labels=dict(draft.labels),
        )

    def bind_approval(
        self,
        manifest: FilingPackageManifest,
        *,
        approver_name: str,
        approved_at_utc: str,
        statement: str,
        package_input: FilingPackageInput | None = None,
        approval_id: str | None = None,
    ) -> tuple[FilingPackageManifest, PackageApproval]:
        """Bind a named human approval to an exact validated package digest.

        Material input drift (when *package_input* is supplied) or non-validated
        state fails closed.
        """
        if not isinstance(manifest, FilingPackageManifest):
            raise TypeError("manifest must be FilingPackageManifest")
        if manifest.state is not FilingPackageState.VALIDATED:
            raise PackageNotValidatedError(
                "approval requires a validated filing package"
            )
        if package_input is not None and not package_inputs_match(
            manifest, package_input
        ):
            raise PackageApprovalInvalidatedError(
                "material inputs no longer match the validated package digest; "
                "approval cannot be bound"
            )
        if manifest.block_reasons or manifest.open_confirmation_ids:
            raise PackageValidationBlockedError(
                "cannot approve a package with open blocks or confirmations",
                block_reasons=manifest.block_reasons,
            )

        approval = PackageApproval(
            approval_id=approval_id or f"appr:{self._id_factory()}",
            package_digest=manifest.package_digest,
            approver_name=approver_name,
            approved_at_utc=approved_at_utc,
            statement=statement,
        )
        reasons = list(manifest.reason_codes)
        reasons.append(FilingPackageReasonCode.APPROVAL_BOUND.value)
        reasons = list(dict.fromkeys(reasons))

        updated = FilingPackageManifest(
            schema_version=manifest.schema_version,
            package_id=manifest.package_id,
            matter_id=manifest.matter_id,
            state=manifest.state,
            package_digest=manifest.package_digest,
            application_type=manifest.application_type,
            proposed_metadata=dict(manifest.proposed_metadata),
            original_files=manifest.original_files,
            rendered_derivatives=manifest.rendered_derivatives,
            operator_checklist=manifest.operator_checklist,
            drawings_inventory=manifest.drawings_inventory,
            rule_pack=manifest.rule_pack,
            prior_art=manifest.prior_art,
            block_reasons=manifest.block_reasons,
            open_confirmation_ids=manifest.open_confirmation_ids,
            reason_codes=tuple(reasons),
            warnings=manifest.warnings,
            source_roots=manifest.source_roots,
            classification=manifest.classification,
            review_state=manifest.review_state,
            portfolio_fact_digest=manifest.portfolio_fact_digest,
            candidate_dates_digest=manifest.candidate_dates_digest,
            approval=approval,
            labels=dict(manifest.labels),
        )
        return updated, approval

    def revalidate_against_inputs(
        self,
        manifest: FilingPackageManifest,
        package_input: FilingPackageInput,
    ) -> FilingPackageManifest:
        """Return *manifest* or an INVALIDATED copy if material inputs drifted.

        Any material input change invalidates prior approval (acceptance).
        """
        if package_inputs_match(manifest, package_input):
            # Still re-check gates in case confirmation/state changed without
            # material digest change (confirmations excluded from digest).
            blocks, open_ids, reasons = evaluate_validation_blocks(
                package_input, package_digest=manifest.package_digest
            )
            if (
                manifest.state is FilingPackageState.VALIDATED
                and not blocks
                and not open_ids
            ):
                return manifest
            if manifest.state is FilingPackageState.VALIDATED and (
                blocks or open_ids
            ):
                return self._invalidate(
                    manifest,
                    extra_blocks=(
                        ValidationBlockReason.HUMAN_CONFIRMATION_REQUIRED.value,
                    )
                    if open_ids
                    else blocks,
                    extra_reasons=(
                        FilingPackageReasonCode.APPROVAL_INVALIDATED.value,
                        FilingPackageReasonCode.PACKAGE_INVALIDATED.value,
                    ),
                )
            return manifest

        return self._invalidate(
            manifest,
            extra_blocks=(
                ValidationBlockReason.MATERIAL_INPUTS_CHANGED.value,
                ValidationBlockReason.DIGEST_MISMATCH.value,
            ),
            extra_reasons=(
                FilingPackageReasonCode.APPROVAL_INVALIDATED.value,
                FilingPackageReasonCode.PACKAGE_INVALIDATED.value,
            ),
        )

    def _invalidate(
        self,
        manifest: FilingPackageManifest,
        *,
        extra_blocks: Sequence[str],
        extra_reasons: Sequence[str],
    ) -> FilingPackageManifest:
        blocks = list(manifest.block_reasons)
        blocks.extend(extra_blocks)
        blocks = list(dict.fromkeys(blocks))
        reasons = list(manifest.reason_codes)
        reasons.extend(extra_reasons)
        reasons = list(dict.fromkeys(reasons))
        return FilingPackageManifest(
            schema_version=manifest.schema_version,
            package_id=manifest.package_id,
            matter_id=manifest.matter_id,
            state=FilingPackageState.INVALIDATED,
            package_digest=manifest.package_digest,
            application_type=manifest.application_type,
            proposed_metadata=dict(manifest.proposed_metadata),
            original_files=manifest.original_files,
            rendered_derivatives=manifest.rendered_derivatives,
            operator_checklist=manifest.operator_checklist,
            drawings_inventory=manifest.drawings_inventory,
            rule_pack=manifest.rule_pack,
            prior_art=manifest.prior_art,
            block_reasons=tuple(blocks),
            open_confirmation_ids=manifest.open_confirmation_ids,
            reason_codes=tuple(reasons),
            warnings=manifest.warnings,
            source_roots=manifest.source_roots,
            classification=manifest.classification,
            review_state=ReviewState.REQUIRED,
            portfolio_fact_digest=manifest.portfolio_fact_digest,
            candidate_dates_digest=manifest.candidate_dates_digest,
            approval=None,  # approval wiped on invalidation
            labels=dict(manifest.labels),
        )


def compile_filing_package(
    package_input: FilingPackageInput,
    *,
    id_factory: Callable[[], str] | None = None,
    package_id: str | None = None,
) -> FilingPackageManifest:
    """Module-level compile helper."""
    return FilingPackageCompiler(id_factory=id_factory).compile(
        package_input, package_id=package_id
    )


def validate_filing_package(
    package_input: FilingPackageInput,
    *,
    id_factory: Callable[[], str] | None = None,
    package_id: str | None = None,
    raise_if_blocked: bool = False,
) -> FilingPackageManifest:
    """Module-level validate helper."""
    return FilingPackageCompiler(id_factory=id_factory).validate(
        package_input,
        package_id=package_id,
        raise_if_blocked=raise_if_blocked,
    )


__all__ = [
    "FILING_PACKAGE_DISCLAIMER",
    "FILING_PACKAGE_INTERFACE",
    "FILING_PACKAGE_RULESET_VERSION",
    "FILING_PACKAGE_SCHEMA_VERSION",
    "FORBIDDEN_PACKAGE_ACTIONS",
    "MANDATORY_CHECKLIST_CATEGORIES",
    "OUTPUT_KIND_FILING_PACKAGE",
    "OUTPUT_KIND_PACKAGE_APPROVAL",
    "PARSER_VERSION",
    "ChecklistCategory",
    "DrawingsInventoryItem",
    "FilingPackageCompiler",
    "FilingPackageError",
    "FilingPackageInput",
    "FilingPackageManifest",
    "FilingPackageReasonCode",
    "FilingPackageState",
    "ForbiddenPackageActionError",
    "MediaKind",
    "OperatorChecklistItem",
    "OriginalFileRole",
    "PackageApproval",
    "PackageApprovalInvalidatedError",
    "PackageArtifactFamily",
    "PackageFileEntry",
    "PackageNotValidatedError",
    "PackageValidationBlockedError",
    "PriorArtCoverageBinding",
    "ProposedAdsField",
    "RulePackBinding",
    "RulePackStatus",
    "ValidationBlockReason",
    "assert_action_allowed",
    "compile_filing_package",
    "confirm_checklist_items",
    "default_mandatory_checklist",
    "evaluate_validation_blocks",
    "is_forbidden_action",
    "package_inputs_match",
    "sha256_hex",
    "validate_filing_package",
]
