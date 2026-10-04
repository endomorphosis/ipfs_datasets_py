"""Governance contracts for the pinned Solidity CPT Top-10 corpus.

This module is deliberately inert.  It records an immutable source profile,
keeps dataset and row license evidence separate, and evaluates publication
requests without downloading, compiling, executing, training, or uploading
anything.  Corpus content is untrusted data and has no proof, safety, or
transaction-enforcement authority.

``top10`` is the dataset author's top-decile quality selection.  It is not an
OWASP Top 10 label, a vulnerability label, or evidence that a contract is
safe.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Any, Final


RELEASE_POLICY_VERSION: Final = "solidity-cpt-top10-release-policy/v1"

SOLIDITY_CPT_DATASET_ID: Final = "samscrack/solidity-cpt-top10-quality"
SOLIDITY_CPT_REVISION: Final = "23c0b2f279fa29c6b425543fe9c8bf41d574d028"
SOLIDITY_CPT_CONFIG_NAME: Final = "default"
SOLIDITY_CPT_SPLIT: Final = "train"
SOLIDITY_CPT_SHARD_PATH: Final = "top10.parquet"
SOLIDITY_CPT_SHARD_SHA256: Final = (
    "185f1ac548f0df10a8166c8a2a10610bcc3422ce77f51567c3de86ddc8f5e455"
)
SOLIDITY_CPT_SHARD_SIZE_BYTES: Final = 109_124_886
SOLIDITY_CPT_ROW_COUNT: Final = 23_471
SOLIDITY_CPT_DATASET_LICENSE: Final = "CC-BY-4.0"
SOLIDITY_CPT_COLUMN_TYPES: Final[tuple[tuple[str, str], ...]] = (
    ("text", "string"),
    ("source", "string"),
    ("address", "string"),
    ("name", "string"),
    ("compiler", "string"),
    ("license", "string"),
    ("path", "string"),
    ("n_chars", "int64"),
)
SOLIDITY_CPT_COLUMNS: Final[tuple[str, ...]] = tuple(
    name for name, _ in SOLIDITY_CPT_COLUMN_TYPES
)

# These capabilities require later, separately reviewed components and grants.
# Unknown capabilities are denied too; this set records the acceptance-critical
# names that must never be inferred from this corpus policy.
DEFAULT_FORBIDDEN_AUTHORITIES: Final[frozenset[str]] = frozenset(
    {"network", "execution", "training", "upload", "proof", "enforcement"}
)

_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_APPROVAL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{2,255}$")
_AMBIGUOUS_LICENSES = frozenset(
    {
        "",
        "custom",
        "n/a",
        "na",
        "no license",
        "no-license",
        "none",
        "not specified",
        "null",
        "other",
        "proprietary",
        "see file",
        "see-file",
        "unknown",
        "unlicensed",
    }
)


class ReleasePolicyError(ValueError):
    """Raised when governance evidence is malformed or inconsistent."""


class SourceProfileError(ReleasePolicyError):
    """Raised when an observation differs from the immutable source pin."""


class PublicationRejectedError(ReleasePolicyError):
    """Raised when a caller requires a publication decision to be admitted."""


class LicenseLayer(str, Enum):
    """The non-interchangeable layers at which license evidence is observed."""

    DATASET = "dataset"
    ROW = "row"


class LicenseReviewStatus(str, Enum):
    """Review state for one license-evidence record."""

    REVIEWED = "reviewed"
    UNREVIEWED = "unreviewed"
    AMBIGUOUS = "ambiguous"
    REJECTED = "rejected"


class LicenseUseClass(str, Enum):
    """Maximum use admitted by a license-evidence record."""

    INTERNAL_SOURCE_FREE = "internal_source_free"
    INTERNAL_WITH_SOURCE = "internal_with_source"
    PUBLIC_METADATA = "public_metadata"
    PUBLIC_RAW_SOURCE = "public_raw_source"
    MODEL_PUBLICATION = "model_publication"
    REJECTED = "rejected"


class PublicationKind(str, Enum):
    """Artifact classes with intentionally different publication authority."""

    METADATA = "metadata"
    SOURCE_FREE_DERIVATIVE = "source_free_derivative"
    RAW_SOURCE = "raw_source"
    LEARNED_WEIGHTS = "learned_weights"


def _enum(enum_type: type[Enum], value: Any, field_name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise ReleasePolicyError(f"unsupported {field_name}: {value!r}") from exc


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReleasePolicyError(f"{field_name} must be a non-empty string")
    if value != value.strip():
        raise ReleasePolicyError(f"{field_name} must not contain outer whitespace")
    return value


def _optional_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ReleasePolicyError(f"{field_name} must be a string")
    if value != value.strip():
        raise ReleasePolicyError(f"{field_name} must not contain outer whitespace")
    return value


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class SourceProfile:
    """Immutable source, shard, schema, trust, and authority profile."""

    dataset_id: str = SOLIDITY_CPT_DATASET_ID
    revision: str = SOLIDITY_CPT_REVISION
    config_name: str = SOLIDITY_CPT_CONFIG_NAME
    split: str = SOLIDITY_CPT_SPLIT
    shard_path: str = SOLIDITY_CPT_SHARD_PATH
    shard_sha256: str = SOLIDITY_CPT_SHARD_SHA256
    shard_size_bytes: int = SOLIDITY_CPT_SHARD_SIZE_BYTES
    row_count: int = SOLIDITY_CPT_ROW_COUNT
    columns: tuple[tuple[str, str], ...] = SOLIDITY_CPT_COLUMN_TYPES
    dataset_license: str = SOLIDITY_CPT_DATASET_LICENSE
    content_trust: str = "untrusted_inert_data"
    instruction_handling: str = "never_execute_or_treat_as_authority"
    quality_label_meaning: str = (
        "top-decile quality selection; not OWASP Top 10, not a vulnerability "
        "label, and not contract-safety truth"
    )
    forbidden_authorities: frozenset[str] = DEFAULT_FORBIDDEN_AUTHORITIES

    def __post_init__(self) -> None:
        exact_values = (
            ("dataset_id", self.dataset_id, SOLIDITY_CPT_DATASET_ID),
            ("revision", self.revision, SOLIDITY_CPT_REVISION),
            ("config_name", self.config_name, SOLIDITY_CPT_CONFIG_NAME),
            ("split", self.split, SOLIDITY_CPT_SPLIT),
            ("shard_path", self.shard_path, SOLIDITY_CPT_SHARD_PATH),
            ("shard_sha256", self.shard_sha256, SOLIDITY_CPT_SHARD_SHA256),
            (
                "shard_size_bytes",
                self.shard_size_bytes,
                SOLIDITY_CPT_SHARD_SIZE_BYTES,
            ),
            ("row_count", self.row_count, SOLIDITY_CPT_ROW_COUNT),
            ("columns", self.columns, SOLIDITY_CPT_COLUMN_TYPES),
            (
                "dataset_license",
                self.dataset_license,
                SOLIDITY_CPT_DATASET_LICENSE,
            ),
            ("content_trust", self.content_trust, "untrusted_inert_data"),
            (
                "instruction_handling",
                self.instruction_handling,
                "never_execute_or_treat_as_authority",
            ),
        )
        for field_name, observed, expected in exact_values:
            if observed != expected:
                raise SourceProfileError(
                    f"{field_name} differs from the reviewed Solidity CPT pin"
                )
        if not _SHA1_RE.fullmatch(self.revision):
            raise SourceProfileError("revision must be a lowercase commit SHA")
        if not _SHA256_RE.fullmatch(self.shard_sha256):
            raise SourceProfileError("shard_sha256 must be lowercase SHA-256")
        if not isinstance(self.forbidden_authorities, frozenset):
            raise SourceProfileError("forbidden_authorities must be a frozenset")
        if not DEFAULT_FORBIDDEN_AUTHORITIES <= self.forbidden_authorities:
            raise SourceProfileError(
                "forbidden_authorities omits an acceptance-critical capability"
            )
        quality = self.quality_label_meaning.casefold()
        for required in ("top-decile", "not owasp", "not a vulnerability", "not contract"):
            if required not in quality:
                raise SourceProfileError(
                    "quality_label_meaning must preserve the non-safety boundary"
                )

    @property
    def ordered_column_names(self) -> tuple[str, ...]:
        return tuple(name for name, _ in self.columns)

    def authority_allows(self, capability: str) -> bool:
        """Return ``False`` for every capability; unknown values fail closed."""

        _required_text(capability, "capability")
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "columns": [
                {"name": name, "type": data_type}
                for name, data_type in self.columns
            ],
            "config_name": self.config_name,
            "content_trust": self.content_trust,
            "dataset_id": self.dataset_id,
            "dataset_license": self.dataset_license,
            "forbidden_authorities": sorted(self.forbidden_authorities),
            "instruction_handling": self.instruction_handling,
            "quality_label_meaning": self.quality_label_meaning,
            "revision": self.revision,
            "row_count": self.row_count,
            "shard_path": self.shard_path,
            "shard_sha256": self.shard_sha256,
            "shard_size_bytes": self.shard_size_bytes,
            "split": self.split,
        }

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical_json_bytes(self.to_dict())).hexdigest()

    def verify_observation(self, observation: Mapping[str, Any]) -> None:
        """Fail closed unless observed Hub/shard facts match this exact pin."""

        if not isinstance(observation, Mapping):
            raise SourceProfileError("source observation must be a mapping")
        required = {
            "dataset_id": self.dataset_id,
            "revision": self.revision,
            "split": self.split,
            "shard_path": self.shard_path,
            "shard_sha256": self.shard_sha256,
            "shard_size_bytes": self.shard_size_bytes,
            "row_count": self.row_count,
        }
        mismatches: list[str] = []
        for field_name, expected in required.items():
            if field_name not in observation:
                mismatches.append(f"{field_name}=missing")
            elif observation[field_name] != expected:
                mismatches.append(f"{field_name}=mismatch")

        if "config_name" in observation and observation["config_name"] != self.config_name:
            mismatches.append("config_name=mismatch")

        observed_columns = observation.get("columns")
        if observed_columns is None:
            mismatches.append("columns=missing")
        elif isinstance(observed_columns, Sequence) and not isinstance(
            observed_columns, (str, bytes, bytearray)
        ):
            normalized = tuple(observed_columns)
            if normalized not in (self.columns, self.ordered_column_names):
                # JSON observations often encode typed tuples as two-item lists.
                try:
                    normalized_pairs = tuple(tuple(item) for item in normalized)
                except TypeError:
                    normalized_pairs = ()
                if normalized_pairs != self.columns:
                    mismatches.append("columns=mismatch")
        else:
            mismatches.append("columns=malformed")

        if mismatches:
            raise SourceProfileError(
                "source profile verification failed: " + ", ".join(mismatches)
            )


@dataclass(frozen=True, slots=True)
class LicenseProvenance:
    """One layer of license evidence, never a legal opinion or operator grant."""

    dataset_id: str
    source_revision: str
    layer: LicenseLayer
    license_expression: str
    review_status: LicenseReviewStatus
    use_class: LicenseUseClass
    evidence_url: str
    reviewed_by: str = ""
    reviewed_at: str = ""
    row_index: int | None = None
    row_license_raw: str = ""
    redistribution_allowed: bool = False
    raw_source_redistribution_allowed: bool = False
    model_publication_allowed: bool = False

    def __post_init__(self) -> None:
        if self.dataset_id != SOLIDITY_CPT_DATASET_ID:
            raise ReleasePolicyError("license dataset_id differs from source pin")
        if self.source_revision != SOLIDITY_CPT_REVISION:
            raise ReleasePolicyError("license source_revision differs from source pin")
        object.__setattr__(self, "layer", _enum(LicenseLayer, self.layer, "layer"))
        object.__setattr__(
            self,
            "review_status",
            _enum(LicenseReviewStatus, self.review_status, "review_status"),
        )
        object.__setattr__(
            self, "use_class", _enum(LicenseUseClass, self.use_class, "use_class")
        )
        _optional_text(self.license_expression, "license_expression")
        _required_text(self.evidence_url, "evidence_url")
        _optional_text(self.reviewed_by, "reviewed_by")
        _optional_text(self.reviewed_at, "reviewed_at")
        _optional_text(self.row_license_raw, "row_license_raw")

        if self.layer is LicenseLayer.DATASET:
            if self.row_index is not None or self.row_license_raw:
                raise ReleasePolicyError(
                    "dataset license evidence cannot contain per-row fields"
                )
        else:
            if type(self.row_index) is not int or self.row_index < 0:
                raise ReleasePolicyError(
                    "row license evidence requires a non-negative row_index"
                )

        if self.review_status is LicenseReviewStatus.REVIEWED:
            if not self.reviewed_by or not self.reviewed_at:
                raise ReleasePolicyError(
                    "reviewed license evidence requires reviewer and timestamp"
                )
        elif self.reviewed_by or self.reviewed_at:
            raise ReleasePolicyError(
                "unreviewed license evidence cannot name review authority"
            )

        if self.use_class is LicenseUseClass.INTERNAL_SOURCE_FREE and (
            self.raw_source_redistribution_allowed
            or self.model_publication_allowed
        ):
            raise ReleasePolicyError(
                "internal/source-free evidence cannot authorize raw source or models"
            )
        if (
            self.raw_source_redistribution_allowed
            or self.model_publication_allowed
        ) and self.review_status is not LicenseReviewStatus.REVIEWED:
            raise ReleasePolicyError(
                "raw source or model publication requires reviewed license evidence"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "evidence_url": self.evidence_url,
            "layer": self.layer.value,
            "license_expression": self.license_expression,
            "model_publication_allowed": self.model_publication_allowed,
            "raw_source_redistribution_allowed": (
                self.raw_source_redistribution_allowed
            ),
            "redistribution_allowed": self.redistribution_allowed,
            "review_status": self.review_status.value,
            "reviewed_at": self.reviewed_at,
            "reviewed_by": self.reviewed_by,
            "row_index": self.row_index,
            "row_license_raw": self.row_license_raw,
            "source_revision": self.source_revision,
            "use_class": self.use_class.value,
        }


def dataset_license_provenance() -> LicenseProvenance:
    """Return reviewed dataset-level evidence without row-level authority."""

    return LicenseProvenance(
        dataset_id=SOLIDITY_CPT_DATASET_ID,
        source_revision=SOLIDITY_CPT_REVISION,
        layer=LicenseLayer.DATASET,
        license_expression=SOLIDITY_CPT_DATASET_LICENSE,
        review_status=LicenseReviewStatus.REVIEWED,
        use_class=LicenseUseClass.PUBLIC_METADATA,
        evidence_url=(
            f"https://huggingface.co/datasets/{SOLIDITY_CPT_DATASET_ID}/blob/"
            f"{SOLIDITY_CPT_REVISION}/README.md"
        ),
        reviewed_by="crypto-ir-governance-baseline",
        reviewed_at="2026-07-30T00:00:00Z",
        redistribution_allowed=True,
    )


def classify_row_license(
    raw_license: Any,
) -> tuple[LicenseReviewStatus, LicenseUseClass, str]:
    """Classify raw row metadata conservatively.

    A recognizable token is still unreviewed evidence, not license approval.
    Absent or ambiguous tokens receive the stricter ``AMBIGUOUS`` status.
    Both cases default to internal/source-free use.
    """

    if raw_license is None:
        normalized = ""
    elif isinstance(raw_license, str):
        normalized = " ".join(raw_license.strip().split())
    else:
        return (
            LicenseReviewStatus.AMBIGUOUS,
            LicenseUseClass.INTERNAL_SOURCE_FREE,
            "",
        )
    status = (
        LicenseReviewStatus.AMBIGUOUS
        if normalized.casefold() in _AMBIGUOUS_LICENSES
        else LicenseReviewStatus.UNREVIEWED
    )
    return status, LicenseUseClass.INTERNAL_SOURCE_FREE, normalized


def row_license_provenance(
    *,
    row_index: int,
    raw_license: Any,
    reviewed: bool = False,
    reviewed_by: str = "",
    reviewed_at: str = "",
    redistribution_allowed: bool = False,
    raw_source_redistribution_allowed: bool = False,
    model_publication_allowed: bool = False,
    use_class: LicenseUseClass | str | None = None,
) -> LicenseProvenance:
    """Create separate per-row license evidence.

    Broader use never follows merely from a license-looking string.  It
    requires explicit review fields and the corresponding independent flags.
    """

    status, default_use, normalized = classify_row_license(raw_license)
    selected_use = default_use if use_class is None else _enum(
        LicenseUseClass, use_class, "use_class"
    )
    if reviewed:
        status = LicenseReviewStatus.REVIEWED
    elif (
        selected_use is not LicenseUseClass.INTERNAL_SOURCE_FREE
        or redistribution_allowed
        or raw_source_redistribution_allowed
        or model_publication_allowed
    ):
        raise ReleasePolicyError(
            "broader row use requires explicit license review"
        )
    return LicenseProvenance(
        dataset_id=SOLIDITY_CPT_DATASET_ID,
        source_revision=SOLIDITY_CPT_REVISION,
        layer=LicenseLayer.ROW,
        license_expression=normalized,
        review_status=status,
        use_class=selected_use,
        evidence_url=(
            f"https://huggingface.co/datasets/{SOLIDITY_CPT_DATASET_ID}/blob/"
            f"{SOLIDITY_CPT_REVISION}/{SOLIDITY_CPT_SHARD_PATH}"
            f"#row-{row_index}"
        ),
        reviewed_by=reviewed_by if reviewed else "",
        reviewed_at=reviewed_at if reviewed else "",
        row_index=row_index,
        row_license_raw=normalized,
        redistribution_allowed=redistribution_allowed,
        raw_source_redistribution_allowed=raw_source_redistribution_allowed,
        model_publication_allowed=model_publication_allowed,
    )


@dataclass(frozen=True, slots=True)
class PublicationAuthority:
    """Separate license-review and operator approvals for sensitive release."""

    kind: PublicationKind
    source_revision: str
    license_review_id: str
    operator_authority_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _enum(PublicationKind, self.kind, "kind"))
        if self.kind not in {
            PublicationKind.RAW_SOURCE,
            PublicationKind.LEARNED_WEIGHTS,
        }:
            raise ReleasePolicyError(
                "publication authority is only valid for sensitive artifacts"
            )
        if self.source_revision != SOLIDITY_CPT_REVISION:
            raise ReleasePolicyError(
                "publication authority is not bound to the pinned revision"
            )
        for field_name, value in (
            ("license_review_id", self.license_review_id),
            ("operator_authority_id", self.operator_authority_id),
        ):
            if not isinstance(value, str) or not _APPROVAL_ID_RE.fullmatch(value):
                raise ReleasePolicyError(
                    f"{field_name} must be a stable, non-empty approval id"
                )
        if self.license_review_id == self.operator_authority_id:
            raise ReleasePolicyError(
                "license review and operator authority must be separate records"
            )

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind.value,
            "license_review_id": self.license_review_id,
            "operator_authority_id": self.operator_authority_id,
            "source_revision": self.source_revision,
        }


@dataclass(frozen=True, slots=True)
class PublicationDecision:
    """Source-free deterministic result of a publication-policy evaluation."""

    admitted: bool
    kind: PublicationKind
    reason_codes: tuple[str, ...]
    source_profile_sha256: str
    policy_sha256: str
    dataset_license: LicenseProvenance
    row_license: LicenseProvenance | None
    authority: PublicationAuthority | None
    proof_authority: bool = False
    enforcement_authority: bool = False

    def __post_init__(self) -> None:
        if self.proof_authority is not False:
            raise ReleasePolicyError(
                "a corpus publication decision cannot have proof authority"
            )
        if self.enforcement_authority is not False:
            raise ReleasePolicyError(
                "a corpus publication decision cannot have enforcement authority"
            )

    def require_admitted(self) -> "PublicationDecision":
        if not self.admitted:
            raise PublicationRejectedError(
                "publication rejected: " + ", ".join(self.reason_codes)
            )
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted": self.admitted,
            "authority": None if self.authority is None else self.authority.to_dict(),
            "dataset_license": self.dataset_license.to_dict(),
            "enforcement_authority": self.enforcement_authority,
            "kind": self.kind.value,
            "policy_sha256": self.policy_sha256,
            "proof_authority": self.proof_authority,
            "reason_codes": list(self.reason_codes),
            "row_license": (
                None if self.row_license is None else self.row_license.to_dict()
            ),
            "source_profile_sha256": self.source_profile_sha256,
        }


@dataclass(frozen=True, slots=True)
class SolidityCPTReleasePolicy:
    """Fail-closed policy for authority and publication decisions."""

    source_profile: SourceProfile = SourceProfile()
    version: str = RELEASE_POLICY_VERSION
    forbidden_authorities: frozenset[str] = DEFAULT_FORBIDDEN_AUTHORITIES
    ambiguous_row_default: LicenseUseClass = LicenseUseClass.INTERNAL_SOURCE_FREE
    raw_source_requires_separate_review: bool = True
    learned_weights_require_separate_review: bool = True

    def __post_init__(self) -> None:
        if self.source_profile != PINNED_SOURCE_PROFILE:
            raise ReleasePolicyError("release policy must use the pinned source profile")
        if self.version != RELEASE_POLICY_VERSION:
            raise ReleasePolicyError("release policy version is not reviewed")
        if not isinstance(self.forbidden_authorities, frozenset):
            raise ReleasePolicyError("forbidden_authorities must be a frozenset")
        if not DEFAULT_FORBIDDEN_AUTHORITIES <= self.forbidden_authorities:
            raise ReleasePolicyError(
                "release policy cannot remove default-denied authorities"
            )
        object.__setattr__(
            self,
            "ambiguous_row_default",
            _enum(LicenseUseClass, self.ambiguous_row_default, "ambiguous_row_default"),
        )
        if self.ambiguous_row_default is not LicenseUseClass.INTERNAL_SOURCE_FREE:
            raise ReleasePolicyError(
                "ambiguous row licenses must default to internal/source-free use"
            )
        if not self.raw_source_requires_separate_review:
            raise ReleasePolicyError("raw source review requirement cannot be disabled")
        if not self.learned_weights_require_separate_review:
            raise ReleasePolicyError(
                "learned-weights review requirement cannot be disabled"
            )

    def authority_allows(self, capability: str) -> bool:
        """Deny ambient authority, including unknown capability names."""

        _required_text(capability, "capability")
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ambiguous_row_default": self.ambiguous_row_default.value,
            "forbidden_authorities": sorted(self.forbidden_authorities),
            "learned_weights_require_separate_review": (
                self.learned_weights_require_separate_review
            ),
            "raw_source_requires_separate_review": (
                self.raw_source_requires_separate_review
            ),
            "source_profile_sha256": self.source_profile.sha256,
            "version": self.version,
        }

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical_json_bytes(self.to_dict())).hexdigest()

    def evaluate_publication(
        self,
        kind: PublicationKind | str,
        *,
        dataset_license: LicenseProvenance | None = None,
        row_license: LicenseProvenance | None = None,
        authority: PublicationAuthority | None = None,
    ) -> PublicationDecision:
        """Evaluate a publication request without performing publication."""

        selected_kind = _enum(PublicationKind, kind, "publication kind")
        dataset_evidence = dataset_license or dataset_license_provenance()
        reasons: list[str] = []

        if dataset_evidence.layer is not LicenseLayer.DATASET:
            reasons.append("license.dataset_layer_required")
        if dataset_evidence.source_revision != self.source_profile.revision:
            reasons.append("license.dataset_revision_mismatch")
        if dataset_evidence.review_status is not LicenseReviewStatus.REVIEWED:
            reasons.append("license.dataset_unreviewed")
        if row_license is not None:
            if row_license.layer is not LicenseLayer.ROW:
                reasons.append("license.row_layer_required")
            if row_license.source_revision != self.source_profile.revision:
                reasons.append("license.row_revision_mismatch")

        if selected_kind in {
            PublicationKind.METADATA,
            PublicationKind.SOURCE_FREE_DERIVATIVE,
        }:
            if row_license is not None and (
                row_license.use_class is LicenseUseClass.REJECTED
                or row_license.review_status is LicenseReviewStatus.REJECTED
            ):
                reasons.append("license.row_rejected")
            if authority is not None:
                reasons.append("authority.unexpected_sensitive_grant")

        elif selected_kind is PublicationKind.RAW_SOURCE:
            if row_license is None:
                reasons.append("license.row_required")
            elif (
                row_license.review_status is not LicenseReviewStatus.REVIEWED
                or not row_license.raw_source_redistribution_allowed
            ):
                reasons.append("license.raw_source_review_required")
            if authority is None:
                reasons.append("authority.operator_required")
            elif authority.kind is not selected_kind:
                reasons.append("authority.kind_mismatch")

        elif selected_kind is PublicationKind.LEARNED_WEIGHTS:
            if row_license is None:
                reasons.append("license.row_required")
            elif (
                row_license.review_status is not LicenseReviewStatus.REVIEWED
                or not row_license.model_publication_allowed
            ):
                reasons.append("license.learned_weights_review_required")
            if authority is None:
                reasons.append("authority.operator_required")
            elif authority.kind is not selected_kind:
                reasons.append("authority.kind_mismatch")

        if authority is not None and authority.source_revision != self.source_profile.revision:
            reasons.append("authority.revision_mismatch")

        return PublicationDecision(
            admitted=not reasons,
            kind=selected_kind,
            reason_codes=tuple(sorted(set(reasons))),
            source_profile_sha256=self.source_profile.sha256,
            policy_sha256=self.sha256,
            dataset_license=dataset_evidence,
            row_license=row_license,
            authority=authority,
        )


PINNED_SOURCE_PROFILE: Final = SourceProfile()
DEFAULT_RELEASE_POLICY: Final = SolidityCPTReleasePolicy()
RELEASE_POLICY_SHA256: Final = DEFAULT_RELEASE_POLICY.sha256


def evaluate_publication_admission(
    kind: PublicationKind | str,
    *,
    dataset_license: LicenseProvenance | None = None,
    row_license: LicenseProvenance | None = None,
    authority: PublicationAuthority | None = None,
) -> PublicationDecision:
    """Evaluate against :data:`DEFAULT_RELEASE_POLICY`."""

    return DEFAULT_RELEASE_POLICY.evaluate_publication(
        kind,
        dataset_license=dataset_license,
        row_license=row_license,
        authority=authority,
    )


__all__ = [
    "DEFAULT_FORBIDDEN_AUTHORITIES",
    "DEFAULT_RELEASE_POLICY",
    "LicenseLayer",
    "LicenseProvenance",
    "LicenseReviewStatus",
    "LicenseUseClass",
    "PINNED_SOURCE_PROFILE",
    "PublicationAuthority",
    "PublicationDecision",
    "PublicationKind",
    "PublicationRejectedError",
    "RELEASE_POLICY_SHA256",
    "RELEASE_POLICY_VERSION",
    "ReleasePolicyError",
    "SOLIDITY_CPT_COLUMNS",
    "SOLIDITY_CPT_COLUMN_TYPES",
    "SOLIDITY_CPT_CONFIG_NAME",
    "SOLIDITY_CPT_DATASET_ID",
    "SOLIDITY_CPT_DATASET_LICENSE",
    "SOLIDITY_CPT_REVISION",
    "SOLIDITY_CPT_ROW_COUNT",
    "SOLIDITY_CPT_SHARD_PATH",
    "SOLIDITY_CPT_SHARD_SHA256",
    "SOLIDITY_CPT_SHARD_SIZE_BYTES",
    "SOLIDITY_CPT_SPLIT",
    "SolidityCPTReleasePolicy",
    "SourceProfile",
    "SourceProfileError",
    "classify_row_license",
    "dataset_license_provenance",
    "evaluate_publication_admission",
    "row_license_provenance",
]
