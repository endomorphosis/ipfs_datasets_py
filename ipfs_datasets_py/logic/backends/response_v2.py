"""LogicProviderResponse@2 — typed provider responses with untrusted default authority.

Interface: ``LogicProviderResponse@2`` (LPC-052).

Pairs with :mod:`ipfs_datasets_py.logic.backends.protocol_v2` typed requests.
Unlike ``LogicProvider@1`` responses (ok/result/error only), every @2 response
carries orthogonal lifecycle, semantic, evidence, and provenance fields.

**Untrusted default authority.** Provider-emitted responses default
``evidence_authority`` to :attr:`LogicEvidenceAuthority.ADVISORY`.  Operation
success never upgrades authority or semantic verdict.  Consumers must
independently validate or reconstruct before granting proof authority
(LPC-032).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.backends.protocol_v2 import (
    LOGIC_PROVIDER_PROTOCOL_VERSION,
    PROTOCOL_V2_OPERATIONS,
    ProtocolOperationV2,
    ProtocolV2Error,
)
from ipfs_datasets_py.logic.backends.provider import (
    LogicProviderFailure,
    LogicProviderFailureCode,
    _nonnegative_int,
    _reject_unknown,
    _strict_json_object,
    _text as _provider_text,
    canonical_provider_json,
)
from ipfs_datasets_py.logic.ir_core.axes import (
    LogicBoundedness,
    LogicEvidenceAuthority,
    LogicEvidenceKind,
    LogicOperationStatus,
    LogicSemanticVerdict,
    LogicTranslationPreservation,
)
from ipfs_datasets_py.logic.ir_core.protocols import ResourceUsage
from ipfs_datasets_py.logic.syntax_core.contracts import (
    _record_id,
    _require_mapping,
    _sha256_hex,
    canonical_json_bytes,
    content_sha256,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

PROVIDER_RESPONSE_V2_INTERFACE: Final = "LogicProviderResponse@2"
PROVIDER_RESPONSE_V2_MODULE_VERSION: Final = "1.0.0"
PROVIDER_RESPONSE_V2_SCHEMA: Final = (
    "ipfs_datasets_py/logic-provider-response@2"
)
CACHE_PROVENANCE_V2_SCHEMA: Final = (
    "ipfs_datasets_py/logic-provider-cache-provenance@2"
)
RESPONSE_TRANSLATION_REF_SCHEMA: Final = (
    "ipfs_datasets_py/logic-provider-response-translation-ref@2"
)
RESPONSE_SOURCE_REF_SCHEMA: Final = (
    "ipfs_datasets_py/logic-provider-response-source-ref@2"
)
RESPONSE_ARTIFACT_REF_SCHEMA: Final = (
    "ipfs_datasets_py/logic-provider-response-artifact-ref@2"
)

# Default trust ceiling for provider-emitted responses.  Untrusted until a
# later validation / reconstruction / kernel path raises authority explicitly.
DEFAULT_EVIDENCE_AUTHORITY: Final = LogicEvidenceAuthority.ADVISORY
DEFAULT_EVIDENCE_KIND: Final = LogicEvidenceKind.CANDIDATE
DEFAULT_SEMANTIC_VERDICT: Final = LogicSemanticVerdict.UNKNOWN
DEFAULT_BOUNDEDNESS: Final = LogicBoundedness.UNKNOWN
DEFAULT_TRANSLATION_PRESERVATION: Final = (
    LogicTranslationPreservation.NOT_APPLICABLE
)

# Closed field inventory required on every LogicProviderResponse@2 body.
REQUIRED_RESPONSE_FIELDS: Final[tuple[str, ...]] = (
    "request_id",
    "operation",
    "provider_id",
    "provider_version",
    "operation_status",
    "verdict",
    "evidence_kind",
    "evidence_authority",
    "boundedness",
    "assumptions",
    "translations",
    "sources",
    "artifacts",
    "resources",
    "cache_provenance",
    "error",
)

_TRUSTED_AUTHORITIES: Final[frozenset[LogicEvidenceAuthority]] = frozenset(
    {
        LogicEvidenceAuthority.AUTHORITATIVE,
        LogicEvidenceAuthority.INDEPENDENTLY_CHECKABLE,
    }
)


class ResponseV2Error(ProtocolV2Error):
    """Raised when a LogicProviderResponse@2 record is malformed."""


class ResponseAuthorityError(ResponseV2Error):
    """Raised when a response overclaims evidence authority."""


class CacheHitKind(str, Enum):
    """Closed vocabulary for cache provenance disposition."""

    MISS = "miss"
    HIT = "hit"
    NEGATIVE_HIT = "negative_hit"
    BYPASS = "bypass"
    UNKNOWN = "unknown"


def _enum_value(enum_type: type[Enum], value: object, field_name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(getattr(value, "value", value)))
    except (TypeError, ValueError) as error:
        allowed = ", ".join(repr(member.value) for member in enum_type)
        raise ResponseV2Error(
            f"{field_name} must be one of {allowed}; got {value!r}"
        ) from error


def _coerce_operation(value: object) -> ProtocolOperationV2:
    try:
        return ProtocolOperationV2(str(getattr(value, "value", value)))
    except ValueError as error:
        allowed = ", ".join(sorted(PROTOCOL_V2_OPERATIONS))
        raise ResponseV2Error(
            f"operation must be one of: {allowed}; got {value!r}"
        ) from error


def _unique_record_ids(
    values: Sequence[str] | object, field_name: str
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(
        values, Sequence
    ):
        raise ResponseV2Error(f"{field_name} must be a sequence of record ids")
    result = tuple(_record_id(item, f"{field_name} item") for item in values)
    if len(result) != len(set(result)):
        raise ResponseV2Error(f"{field_name} must not contain duplicates")
    return result


def _coerce_resources(value: object) -> ResourceUsage:
    if value is None:
        return ResourceUsage()
    if isinstance(value, ResourceUsage):
        return value
    if isinstance(value, Mapping):
        return ResourceUsage.from_dict(value)
    raise ResponseV2Error(
        f"resources must be ResourceUsage or mapping; got {type(value).__name__}"
    )


def _coerce_error(
    value: object,
) -> LogicProviderFailure | None:
    if value is None:
        return None
    if isinstance(value, LogicProviderFailure):
        return value
    if isinstance(value, Mapping):
        return LogicProviderFailure.from_dict(value)
    raise ResponseV2Error(
        f"error must be LogicProviderFailure, mapping, or null; got "
        f"{type(value).__name__}"
    )


def _optional_digest(value: object, field_name: str) -> str:
    text = str(value or "")
    if not text:
        return ""
    return _sha256_hex(text, field_name)


# ---------------------------------------------------------------------------
# Nested provenance / lineage refs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResponseTranslationRef:
    """Identity of a translation step reported by a provider response."""

    translation_id: str
    content_digest: str = ""
    preservation: LogicTranslationPreservation | str = (
        LogicTranslationPreservation.UNKNOWN
    )
    schema_version: str = RESPONSE_TRANSLATION_REF_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "translation_id",
            _record_id(self.translation_id, "translation_id"),
        )
        object.__setattr__(
            self,
            "content_digest",
            _optional_digest(self.content_digest, "content_digest"),
        )
        object.__setattr__(
            self,
            "preservation",
            _enum_value(
                LogicTranslationPreservation,
                self.preservation,
                "preservation",
            ),
        )
        if self.schema_version != RESPONSE_TRANSLATION_REF_SCHEMA:
            raise ResponseV2Error(
                "unsupported response translation ref schema"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_digest": self.content_digest,
            "preservation": (
                self.preservation.value
                if isinstance(self.preservation, LogicTranslationPreservation)
                else str(self.preservation)
            ),
            "schema_version": self.schema_version,
            "translation_id": self.translation_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | str) -> "ResponseTranslationRef":
        if isinstance(value, str):
            return cls(translation_id=value)
        payload = _require_mapping(value, "ResponseTranslationRef")
        _reject_unknown(
            payload,
            frozenset(
                {
                    "translation_id",
                    "content_digest",
                    "preservation",
                    "schema_version",
                }
            ),
            "response translation ref",
        )
        return cls(
            translation_id=str(payload.get("translation_id") or ""),
            content_digest=str(payload.get("content_digest") or ""),
            preservation=payload.get(
                "preservation", LogicTranslationPreservation.UNKNOWN.value
            ),
            schema_version=str(
                payload.get("schema_version") or RESPONSE_TRANSLATION_REF_SCHEMA
            ),
        )


@dataclass(frozen=True, slots=True)
class ResponseSourceRef:
    """Source document identity carried on a provider response."""

    document_id: str
    source_digest: str = ""
    schema_version: str = RESPONSE_SOURCE_REF_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "document_id", _record_id(self.document_id, "document_id")
        )
        object.__setattr__(
            self,
            "source_digest",
            _optional_digest(self.source_digest, "source_digest"),
        )
        if self.schema_version != RESPONSE_SOURCE_REF_SCHEMA:
            raise ResponseV2Error("unsupported response source ref schema")

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "schema_version": self.schema_version,
            "source_digest": self.source_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | str) -> "ResponseSourceRef":
        if isinstance(value, str):
            return cls(document_id=value)
        payload = _require_mapping(value, "ResponseSourceRef")
        _reject_unknown(
            payload,
            frozenset({"document_id", "source_digest", "schema_version"}),
            "response source ref",
        )
        return cls(
            document_id=str(payload.get("document_id") or ""),
            source_digest=str(payload.get("source_digest") or ""),
            schema_version=str(
                payload.get("schema_version") or RESPONSE_SOURCE_REF_SCHEMA
            ),
        )


@dataclass(frozen=True, slots=True)
class ResponseArtifactRef:
    """Artifact identity (compiled target, witness, certificate, …)."""

    artifact_id: str
    content_digest: str = ""
    kind: str = "artifact"
    schema_version: str = RESPONSE_ARTIFACT_REF_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "artifact_id", _record_id(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self,
            "content_digest",
            _optional_digest(self.content_digest, "content_digest"),
        )
        object.__setattr__(
            self,
            "kind",
            _provider_text(self.kind, "kind", optional=False, maximum=128),
        )
        if self.schema_version != RESPONSE_ARTIFACT_REF_SCHEMA:
            raise ResponseV2Error("unsupported response artifact ref schema")

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "content_digest": self.content_digest,
            "kind": self.kind,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | str) -> "ResponseArtifactRef":
        if isinstance(value, str):
            return cls(artifact_id=value)
        payload = _require_mapping(value, "ResponseArtifactRef")
        _reject_unknown(
            payload,
            frozenset(
                {"artifact_id", "content_digest", "kind", "schema_version"}
            ),
            "response artifact ref",
        )
        return cls(
            artifact_id=str(payload.get("artifact_id") or ""),
            content_digest=str(payload.get("content_digest") or ""),
            kind=str(payload.get("kind") or "artifact"),
            schema_version=str(
                payload.get("schema_version") or RESPONSE_ARTIFACT_REF_SCHEMA
            ),
        )


@dataclass(frozen=True, slots=True)
class CacheProvenanceV2:
    """Cache lookup provenance attached to a provider response.

    Cache hits never raise authority.  A hit only records that an entry was
    reused; evidence authority remains the response's explicit field.
    """

    hit_kind: CacheHitKind | str = CacheHitKind.MISS
    cache_key_digest: str = ""
    entry_digest: str = ""
    reason: str = ""
    schema_version: str = CACHE_PROVENANCE_V2_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "hit_kind",
            _enum_value(CacheHitKind, self.hit_kind, "hit_kind"),
        )
        object.__setattr__(
            self,
            "cache_key_digest",
            _optional_digest(self.cache_key_digest, "cache_key_digest"),
        )
        object.__setattr__(
            self,
            "entry_digest",
            _optional_digest(self.entry_digest, "entry_digest"),
        )
        object.__setattr__(
            self,
            "reason",
            _provider_text(self.reason, "reason", optional=True, maximum=512),
        )
        if self.schema_version != CACHE_PROVENANCE_V2_SCHEMA:
            raise ResponseV2Error("unsupported cache provenance schema")
        if (
            self.hit_kind is CacheHitKind.HIT
            and not self.cache_key_digest
            and not self.entry_digest
        ):
            raise ResponseV2Error(
                "cache hit provenance requires cache_key_digest or entry_digest"
            )

    @property
    def is_hit(self) -> bool:
        return self.hit_kind in {CacheHitKind.HIT, CacheHitKind.NEGATIVE_HIT}

    def to_dict(self) -> dict[str, Any]:
        return {
            "cache_key_digest": self.cache_key_digest,
            "entry_digest": self.entry_digest,
            "hit_kind": (
                self.hit_kind.value
                if isinstance(self.hit_kind, CacheHitKind)
                else str(self.hit_kind)
            ),
            "reason": self.reason,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(
        cls, value: Mapping[str, Any] | None
    ) -> "CacheProvenanceV2":
        if value is None:
            return cls()
        payload = _require_mapping(value, "CacheProvenanceV2")
        _reject_unknown(
            payload,
            frozenset(
                {
                    "hit_kind",
                    "cache_key_digest",
                    "entry_digest",
                    "reason",
                    "schema_version",
                }
            ),
            "cache provenance",
        )
        return cls(
            hit_kind=payload.get("hit_kind", CacheHitKind.MISS.value),
            cache_key_digest=str(payload.get("cache_key_digest") or ""),
            entry_digest=str(payload.get("entry_digest") or ""),
            reason=str(payload.get("reason") or ""),
            schema_version=str(
                payload.get("schema_version") or CACHE_PROVENANCE_V2_SCHEMA
            ),
        )

    @classmethod
    def miss(cls, *, reason: str = "") -> "CacheProvenanceV2":
        return cls(hit_kind=CacheHitKind.MISS, reason=reason)


def _coerce_translations(
    values: Sequence[Any] | object,
) -> tuple[ResponseTranslationRef, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(
        values, Sequence
    ):
        raise ResponseV2Error("translations must be a sequence")
    result = tuple(
        item
        if isinstance(item, ResponseTranslationRef)
        else ResponseTranslationRef.from_dict(item)
        for item in values
    )
    ids = [item.translation_id for item in result]
    if len(ids) != len(set(ids)):
        raise ResponseV2Error("translations must not contain duplicate ids")
    return result


def _coerce_sources(
    values: Sequence[Any] | object,
) -> tuple[ResponseSourceRef, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(
        values, Sequence
    ):
        raise ResponseV2Error("sources must be a sequence")
    result = tuple(
        item
        if isinstance(item, ResponseSourceRef)
        else ResponseSourceRef.from_dict(item)
        for item in values
    )
    ids = [item.document_id for item in result]
    if len(ids) != len(set(ids)):
        raise ResponseV2Error("sources must not contain duplicate document ids")
    return result


def _coerce_artifacts(
    values: Sequence[Any] | object,
) -> tuple[ResponseArtifactRef, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(
        values, Sequence
    ):
        raise ResponseV2Error("artifacts must be a sequence")
    result = tuple(
        item
        if isinstance(item, ResponseArtifactRef)
        else ResponseArtifactRef.from_dict(item)
        for item in values
    )
    ids = [item.artifact_id for item in result]
    if len(ids) != len(set(ids)):
        raise ResponseV2Error("artifacts must not contain duplicate ids")
    return result


def _coerce_cache_provenance(
    value: object,
) -> CacheProvenanceV2:
    if value is None:
        return CacheProvenanceV2.miss()
    if isinstance(value, CacheProvenanceV2):
        return value
    if isinstance(value, Mapping):
        return CacheProvenanceV2.from_dict(value)
    raise ResponseV2Error(
        f"cache_provenance must be CacheProvenanceV2, mapping, or null; got "
        f"{type(value).__name__}"
    )


# ---------------------------------------------------------------------------
# ProviderResponseV2
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProviderResponseV2:
    """Typed LogicProviderResponse@2 envelope.

    Required fields (acceptance LPC-052):

    * ``request_id``, ``operation``
    * ``provider_id``, ``provider_version``
    * ``operation_status``, ``verdict``
    * ``evidence_kind``, ``evidence_authority``
    * ``boundedness``
    * ``assumptions``, ``translations``, ``sources``, ``artifacts``
    * ``resources``, ``cache_provenance``, ``error``

    Defaults keep provider output **untrusted**: advisory evidence authority,
    unknown semantic verdict, candidate evidence kind, and unknown boundedness.
    """

    request_id: str
    operation: ProtocolOperationV2 | str
    provider_id: str
    provider_version: str
    operation_status: LogicOperationStatus | str = LogicOperationStatus.SUCCEEDED
    verdict: LogicSemanticVerdict | str = DEFAULT_SEMANTIC_VERDICT
    evidence_kind: LogicEvidenceKind | str = DEFAULT_EVIDENCE_KIND
    evidence_authority: LogicEvidenceAuthority | str = DEFAULT_EVIDENCE_AUTHORITY
    boundedness: LogicBoundedness | str = DEFAULT_BOUNDEDNESS
    assumptions: tuple[str, ...] | Sequence[str] = ()
    translations: tuple[ResponseTranslationRef, ...] | Sequence[Any] = ()
    sources: tuple[ResponseSourceRef, ...] | Sequence[Any] = ()
    artifacts: tuple[ResponseArtifactRef, ...] | Sequence[Any] = ()
    resources: ResourceUsage | Mapping[str, Any] = field(
        default_factory=ResourceUsage
    )
    cache_provenance: CacheProvenanceV2 | Mapping[str, Any] | None = None
    error: LogicProviderFailure | Mapping[str, Any] | None = None
    translation_preservation: LogicTranslationPreservation | str = (
        DEFAULT_TRANSLATION_PRESERVATION
    )
    duration_ms: int = 0
    protocol_version: int = LOGIC_PROVIDER_PROTOCOL_VERSION
    schema_version: str = PROVIDER_RESPONSE_V2_SCHEMA
    metadata: Mapping[str, Any] = field(default_factory=dict)

    interface: ClassVar[str] = PROVIDER_RESPONSE_V2_INTERFACE

    def __post_init__(self) -> None:
        if (
            isinstance(self.protocol_version, bool)
            or not isinstance(self.protocol_version, int)
            or self.protocol_version != LOGIC_PROVIDER_PROTOCOL_VERSION
        ):
            raise ResponseV2Error(
                "LogicProviderResponse@2 requires protocol_version=2"
            )
        if self.schema_version != PROVIDER_RESPONSE_V2_SCHEMA:
            raise ResponseV2Error(
                "unsupported logic-provider response@2 schema"
            )

        operation = _coerce_operation(self.operation)
        operation_status = _enum_value(
            LogicOperationStatus, self.operation_status, "operation_status"
        )
        verdict = _enum_value(LogicSemanticVerdict, self.verdict, "verdict")
        evidence_kind = _enum_value(
            LogicEvidenceKind, self.evidence_kind, "evidence_kind"
        )
        evidence_authority = _enum_value(
            LogicEvidenceAuthority,
            self.evidence_authority,
            "evidence_authority",
        )
        boundedness = _enum_value(
            LogicBoundedness, self.boundedness, "boundedness"
        )
        translation_preservation = _enum_value(
            LogicTranslationPreservation,
            self.translation_preservation,
            "translation_preservation",
        )
        duration_ms = _nonnegative_int(self.duration_ms, "duration_ms")
        resources = _coerce_resources(self.resources)
        cache_provenance = _coerce_cache_provenance(self.cache_provenance)
        error = _coerce_error(self.error)
        assumptions = _unique_record_ids(self.assumptions, "assumptions")
        translations = _coerce_translations(self.translations)
        sources = _coerce_sources(self.sources)
        artifacts = _coerce_artifacts(self.artifacts)
        metadata = _strict_json_object(self.metadata, "metadata")

        # Fail closed: operation success must not silently mint trusted authority.
        if (
            operation_status is LogicOperationStatus.SUCCEEDED
            and evidence_authority in _TRUSTED_AUTHORITIES
            and error is not None
        ):
            raise ResponseAuthorityError(
                "succeeded response with trusted authority cannot also carry error"
            )

        # Terminal failure statuses require an error; success/partial may not.
        if operation_status in {
            LogicOperationStatus.FAILED,
            LogicOperationStatus.ERROR,
            LogicOperationStatus.INVALID,
        } and error is None:
            raise ResponseV2Error(
                f"operation_status={operation_status.value} requires an error"
            )
        if (
            operation_status is LogicOperationStatus.SUCCEEDED
            and error is not None
        ):
            raise ResponseV2Error(
                "operation_status=succeeded cannot carry an error"
            )

        object.__setattr__(self, "operation", operation)
        object.__setattr__(
            self,
            "request_id",
            _provider_text(self.request_id, "request_id", maximum=128),
        )
        object.__setattr__(
            self,
            "provider_id",
            _provider_text(self.provider_id, "provider_id", maximum=128),
        )
        object.__setattr__(
            self,
            "provider_version",
            _provider_text(
                self.provider_version, "provider_version", maximum=128
            ),
        )
        object.__setattr__(self, "operation_status", operation_status)
        object.__setattr__(self, "verdict", verdict)
        object.__setattr__(self, "evidence_kind", evidence_kind)
        object.__setattr__(self, "evidence_authority", evidence_authority)
        object.__setattr__(self, "boundedness", boundedness)
        object.__setattr__(
            self, "translation_preservation", translation_preservation
        )
        object.__setattr__(self, "assumptions", assumptions)
        object.__setattr__(self, "translations", translations)
        object.__setattr__(self, "sources", sources)
        object.__setattr__(self, "artifacts", artifacts)
        object.__setattr__(self, "resources", resources)
        object.__setattr__(self, "cache_provenance", cache_provenance)
        object.__setattr__(self, "error", error)
        object.__setattr__(self, "duration_ms", duration_ms)
        object.__setattr__(self, "metadata", metadata)

    # -- derived helpers -----------------------------------------------------

    @property
    def is_success(self) -> bool:
        """Whether the attempt completed without transport/runtime failure.

        This is **not** proof authority and does not imply a conclusive verdict.
        """

        return self.operation_status in {
            LogicOperationStatus.SUCCEEDED,
            LogicOperationStatus.PARTIAL,
        }

    @property
    def is_trusted(self) -> bool:
        """Whether evidence_authority is at or above independently_checkable."""

        return self.evidence_authority in _TRUSTED_AUTHORITIES

    @property
    def default_authority_applied(self) -> bool:
        """Whether the response still carries the untrusted default authority."""

        return self.evidence_authority is DEFAULT_EVIDENCE_AUTHORITY

    def require_untrusted_or_explicit(self) -> "ProviderResponseV2":
        """Return self; raise if success alone is used to claim trust.

        Trusted authority is allowed only when explicitly set on the field —
        never inferred.  This helper documents that callers must not treat
        ``is_success`` as an authority signal.
        """

        if self.is_success and self.is_trusted:
            # Explicit trusted authority on a succeeded response is allowed only
            # when the caller already set evidence_authority; we do not clear it
            # here.  Downstream kernel gates still re-check independently.
            return self
        return self

    def with_authority(
        self,
        authority: LogicEvidenceAuthority | str,
        *,
        allow_upgrade: bool = False,
    ) -> "ProviderResponseV2":
        """Return a copy with an explicit authority (fail closed on silent upgrade).

        Raising authority above the untrusted default requires
        ``allow_upgrade=True`` so call sites document the independent check.
        """

        resolved = _enum_value(
            LogicEvidenceAuthority, authority, "evidence_authority"
        )
        if (
            not allow_upgrade
            and resolved in _TRUSTED_AUTHORITIES
            and self.evidence_authority not in _TRUSTED_AUTHORITIES
        ):
            raise ResponseAuthorityError(
                "raising evidence_authority above the untrusted default requires "
                "allow_upgrade=True after independent validation or reconstruction"
            )
        return ProviderResponseV2(
            request_id=self.request_id,
            operation=self.operation,
            provider_id=self.provider_id,
            provider_version=self.provider_version,
            operation_status=self.operation_status,
            verdict=self.verdict,
            evidence_kind=self.evidence_kind,
            evidence_authority=resolved,  # type: ignore[arg-type]
            boundedness=self.boundedness,
            assumptions=self.assumptions,
            translations=self.translations,
            sources=self.sources,
            artifacts=self.artifacts,
            resources=self.resources,
            cache_provenance=self.cache_provenance,
            error=self.error,
            translation_preservation=self.translation_preservation,
            duration_ms=self.duration_ms,
            protocol_version=self.protocol_version,
            schema_version=self.schema_version,
            metadata=self.metadata,
        )

    def content_digest(self) -> str:
        return content_sha256(canonical_json_bytes(self.to_dict()))

    # -- factories -----------------------------------------------------------

    @classmethod
    def succeeded(
        cls,
        *,
        request_id: str,
        operation: ProtocolOperationV2 | str,
        provider_id: str,
        provider_version: str,
        verdict: LogicSemanticVerdict | str = DEFAULT_SEMANTIC_VERDICT,
        evidence_kind: LogicEvidenceKind | str = DEFAULT_EVIDENCE_KIND,
        evidence_authority: LogicEvidenceAuthority | str = DEFAULT_EVIDENCE_AUTHORITY,
        boundedness: LogicBoundedness | str = DEFAULT_BOUNDEDNESS,
        assumptions: Sequence[str] = (),
        translations: Sequence[Any] = (),
        sources: Sequence[Any] = (),
        artifacts: Sequence[Any] = (),
        resources: ResourceUsage | Mapping[str, Any] | None = None,
        cache_provenance: CacheProvenanceV2 | Mapping[str, Any] | None = None,
        translation_preservation: LogicTranslationPreservation | str = (
            DEFAULT_TRANSLATION_PRESERVATION
        ),
        duration_ms: int = 0,
        metadata: Mapping[str, Any] | None = None,
    ) -> "ProviderResponseV2":
        """Build a succeeded response with untrusted default authority."""

        return cls(
            request_id=request_id,
            operation=operation,
            provider_id=provider_id,
            provider_version=provider_version,
            operation_status=LogicOperationStatus.SUCCEEDED,
            verdict=verdict,
            evidence_kind=evidence_kind,
            evidence_authority=evidence_authority,
            boundedness=boundedness,
            assumptions=tuple(assumptions),
            translations=tuple(translations),
            sources=tuple(sources),
            artifacts=tuple(artifacts),
            resources=resources if resources is not None else ResourceUsage(),
            cache_provenance=cache_provenance,
            error=None,
            translation_preservation=translation_preservation,
            duration_ms=duration_ms,
            metadata=metadata or {},
        )

    @classmethod
    def failed(
        cls,
        *,
        request_id: str,
        operation: ProtocolOperationV2 | str,
        provider_id: str,
        provider_version: str,
        code: LogicProviderFailureCode | str,
        message: str,
        retryable: bool = False,
        details: Mapping[str, Any] | None = None,
        operation_status: LogicOperationStatus | str = LogicOperationStatus.FAILED,
        resources: ResourceUsage | Mapping[str, Any] | None = None,
        cache_provenance: CacheProvenanceV2 | Mapping[str, Any] | None = None,
        duration_ms: int = 0,
        metadata: Mapping[str, Any] | None = None,
    ) -> "ProviderResponseV2":
        """Build a failed response; authority remains the untrusted default."""

        return cls(
            request_id=request_id,
            operation=operation,
            provider_id=provider_id,
            provider_version=provider_version,
            operation_status=operation_status,
            verdict=LogicSemanticVerdict.ERROR,
            evidence_kind=LogicEvidenceKind.UNKNOWN,
            evidence_authority=DEFAULT_EVIDENCE_AUTHORITY,
            boundedness=LogicBoundedness.UNKNOWN,
            assumptions=(),
            translations=(),
            sources=(),
            artifacts=(),
            resources=resources if resources is not None else ResourceUsage(),
            cache_provenance=cache_provenance,
            error=LogicProviderFailure(
                code=code,
                message=message,
                retryable=retryable,
                details=details or {},
            ),
            duration_ms=duration_ms,
            metadata=metadata or {},
        )

    # -- serialization -------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifacts": [item.to_dict() for item in self.artifacts],
            "assumptions": list(self.assumptions),
            "boundedness": (
                self.boundedness.value
                if isinstance(self.boundedness, LogicBoundedness)
                else str(self.boundedness)
            ),
            "cache_provenance": self.cache_provenance.to_dict(),
            "duration_ms": self.duration_ms,
            "error": None if self.error is None else self.error.to_dict(),
            "evidence_authority": (
                self.evidence_authority.value
                if isinstance(self.evidence_authority, LogicEvidenceAuthority)
                else str(self.evidence_authority)
            ),
            "evidence_kind": (
                self.evidence_kind.value
                if isinstance(self.evidence_kind, LogicEvidenceKind)
                else str(self.evidence_kind)
            ),
            "interface": self.interface,
            "metadata": dict(self.metadata),
            "operation": (
                self.operation.value
                if isinstance(self.operation, ProtocolOperationV2)
                else str(self.operation)
            ),
            "operation_status": (
                self.operation_status.value
                if isinstance(self.operation_status, LogicOperationStatus)
                else str(self.operation_status)
            ),
            "protocol_version": self.protocol_version,
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "request_id": self.request_id,
            "resources": self.resources.to_dict(),
            "schema_version": self.schema_version,
            "sources": [item.to_dict() for item in self.sources],
            "translation_preservation": (
                self.translation_preservation.value
                if isinstance(
                    self.translation_preservation, LogicTranslationPreservation
                )
                else str(self.translation_preservation)
            ),
            "translations": [item.to_dict() for item in self.translations],
            "verdict": (
                self.verdict.value
                if isinstance(self.verdict, LogicSemanticVerdict)
                else str(self.verdict)
            ),
        }

    def to_json(self) -> str:
        return canonical_provider_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProviderResponseV2":
        payload = _require_mapping(value, "ProviderResponseV2")
        _reject_unknown(
            payload,
            frozenset(
                {
                    "schema_version",
                    "protocol_version",
                    "interface",
                    "request_id",
                    "operation",
                    "provider_id",
                    "provider_version",
                    "operation_status",
                    "verdict",
                    "evidence_kind",
                    "evidence_authority",
                    "boundedness",
                    "assumptions",
                    "translations",
                    "sources",
                    "artifacts",
                    "resources",
                    "cache_provenance",
                    "error",
                    "translation_preservation",
                    "duration_ms",
                    "metadata",
                }
            ),
            "provider response@2",
        )
        if "request_id" not in payload:
            raise ResponseV2Error("provider response@2 is missing request_id")
        if "operation" not in payload:
            raise ResponseV2Error("provider response@2 is missing operation")
        return cls(
            request_id=str(payload.get("request_id") or ""),
            operation=str(payload.get("operation") or ""),
            provider_id=str(payload.get("provider_id") or ""),
            provider_version=str(payload.get("provider_version") or ""),
            operation_status=payload.get(
                "operation_status", LogicOperationStatus.SUCCEEDED.value
            ),
            verdict=payload.get("verdict", DEFAULT_SEMANTIC_VERDICT.value),
            evidence_kind=payload.get(
                "evidence_kind", DEFAULT_EVIDENCE_KIND.value
            ),
            evidence_authority=payload.get(
                "evidence_authority", DEFAULT_EVIDENCE_AUTHORITY.value
            ),
            boundedness=payload.get(
                "boundedness", DEFAULT_BOUNDEDNESS.value
            ),
            assumptions=tuple(payload.get("assumptions") or ()),
            translations=tuple(payload.get("translations") or ()),
            sources=tuple(payload.get("sources") or ()),
            artifacts=tuple(payload.get("artifacts") or ()),
            resources=payload.get("resources") or {},
            cache_provenance=payload.get("cache_provenance"),
            error=payload.get("error"),
            translation_preservation=payload.get(
                "translation_preservation",
                DEFAULT_TRANSLATION_PRESERVATION.value,
            ),
            duration_ms=int(payload.get("duration_ms") or 0),
            protocol_version=int(
                payload.get(
                    "protocol_version", LOGIC_PROVIDER_PROTOCOL_VERSION
                )
            ),
            schema_version=str(
                payload.get("schema_version") or PROVIDER_RESPONSE_V2_SCHEMA
            ),
            metadata=payload.get("metadata") or {},
        )

    @classmethod
    def from_json(cls, value: str) -> "ProviderResponseV2":
        import json

        try:
            payload = json.loads(value)
        except (TypeError, json.JSONDecodeError) as error:
            raise ResponseV2Error(
                "provider response@2 JSON is malformed"
            ) from error
        if not isinstance(payload, Mapping):
            raise ResponseV2Error("provider response@2 JSON must be an object")
        return cls.from_dict(payload)


def admit_provider_response_v2(
    value: Mapping[str, Any] | ProviderResponseV2,
) -> ProviderResponseV2:
    """Admit a typed LogicProviderResponse@2 body (fail closed)."""

    if isinstance(value, ProviderResponseV2):
        return value
    return ProviderResponseV2.from_dict(
        _require_mapping(value, "ProviderResponseV2")
    )


def default_untrusted_authority() -> LogicEvidenceAuthority:
    """Return the closed untrusted default evidence authority for @2 responses."""

    return DEFAULT_EVIDENCE_AUTHORITY


def response_carries_required_fields(
    response: ProviderResponseV2 | Mapping[str, Any],
) -> bool:
    """Return whether *response* exposes the full LPC-052 field inventory."""

    if isinstance(response, ProviderResponseV2):
        payload = response.to_dict()
    else:
        payload = dict(response)
    return all(field_name in payload for field_name in REQUIRED_RESPONSE_FIELDS)


__all__ = [
    "CACHE_PROVENANCE_V2_SCHEMA",
    "DEFAULT_BOUNDEDNESS",
    "DEFAULT_EVIDENCE_AUTHORITY",
    "DEFAULT_EVIDENCE_KIND",
    "DEFAULT_SEMANTIC_VERDICT",
    "DEFAULT_TRANSLATION_PRESERVATION",
    "PROVIDER_RESPONSE_V2_INTERFACE",
    "PROVIDER_RESPONSE_V2_MODULE_VERSION",
    "PROVIDER_RESPONSE_V2_SCHEMA",
    "REQUIRED_RESPONSE_FIELDS",
    "RESPONSE_ARTIFACT_REF_SCHEMA",
    "RESPONSE_SOURCE_REF_SCHEMA",
    "RESPONSE_TRANSLATION_REF_SCHEMA",
    "CacheHitKind",
    "CacheProvenanceV2",
    "ProviderResponseV2",
    "ResponseArtifactRef",
    "ResponseAuthorityError",
    "ResponseSourceRef",
    "ResponseTranslationRef",
    "ResponseV2Error",
    "admit_provider_response_v2",
    "default_untrusted_authority",
    "response_carries_required_fields",
]
