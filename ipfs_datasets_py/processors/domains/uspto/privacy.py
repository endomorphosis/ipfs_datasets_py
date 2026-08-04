"""USPTO privacy boundary: classification gates, public sinks, and vault separation.

Fail-closed policy for private bytes, extracted text, embeddings, and content
identifiers. Credentials use a secrets vault; document material never does.
Unknown classification quarantines and cannot dispatch to public sinks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, Iterable, Mapping, Sequence

from .contracts import (
    DisclosureClassification,
    is_private_classification,
    is_public_classification,
    most_restrictive_classification,
    requires_quarantine,
)

PRIVACY_POLICY_SCHEMA_VERSION: Final = "uspto.privacy.v1"
PRIVACY_INTERFACE: Final = "UsptoPrivacyPolicy@1"


class PublicSink(str, Enum):
    """Surfaces that must never receive private USPTO material."""

    PUBLIC_IPFS = "public_ipfs"
    PUBLIC_DATASET = "public_dataset"
    PUBLIC_CACHE = "public_cache"
    REMOTE_PROMPT = "remote_prompt"
    LOGS = "logs"
    TELEMETRY = "telemetry"
    JUSTICE_DAO = "justice_dao_hugging_face"


class ContentKind(str, Enum):
    """Kinds of material subject to isolation checks."""

    DOCUMENT_BYTES = "document_bytes"
    EXTRACTED_TEXT = "extracted_text"
    EMBEDDING = "embedding"
    CONTENT_IDENTIFIER = "content_identifier"
    GRAPH_CONTENT = "graph_content"
    METADATA_DIGEST = "metadata_digest"
    CREDENTIAL_SECRET = "credential_secret"


class VaultKind(str, Enum):
    """Storage abstractions with a hard separation of concerns."""

    CREDENTIALS = "credentials_vault"
    DOCUMENT = "document_vault"


class SinkDecisionCode(str, Enum):
    ALLOWED = "allowed"
    DENIED_PRIVATE = "denied_private"
    DENIED_QUARANTINE = "denied_quarantine"
    DENIED_CREDENTIAL = "denied_credential"
    DENIED_EXPORT_REVIEW = "denied_export_review"
    DENIED_CONTENT_KIND = "denied_content_kind"
    DENIED_UNKNOWN_SINK = "denied_unknown_sink"


class VaultDecisionCode(str, Enum):
    ALLOWED = "allowed"
    DENIED_CREDENTIALS_AS_DOCUMENT = "denied_credentials_vault_document_store"
    DENIED_DOCUMENT_AS_CREDENTIAL = "denied_document_vault_credential_secret"
    DENIED_QUARANTINE = "denied_quarantine"
    DENIED_CLASSIFICATION = "denied_classification"


class PrivacyBoundaryError(Exception):
    """Raised when a privacy boundary would be violated."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        classification: str | None = None,
        sink: str | None = None,
        content_kind: str | None = None,
        vault: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.classification = classification
        self.sink = sink
        self.content_kind = content_kind
        self.vault = vault

    def audit_dict(self) -> dict[str, str]:
        """Safe audit payload: reason codes only, never matched private content."""
        out: dict[str, str] = {"code": self.code, "message": str(self)}
        if self.classification is not None:
            out["classification"] = self.classification
        if self.sink is not None:
            out["sink"] = self.sink
        if self.content_kind is not None:
            out["content_kind"] = self.content_kind
        if self.vault is not None:
            out["vault"] = self.vault
        return out


@dataclass(frozen=True, slots=True)
class SinkAdmissionDecision:
    """Result of evaluating whether material may enter a public sink."""

    allowed: bool
    code: SinkDecisionCode
    classification: DisclosureClassification
    sink: PublicSink
    content_kind: ContentKind
    reason: str
    quarantined: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "classification": self.classification.value,
            "code": self.code.value,
            "content_kind": self.content_kind.value,
            "quarantined": self.quarantined,
            "reason": self.reason,
            "sink": self.sink.value,
        }


@dataclass(frozen=True, slots=True)
class VaultAdmissionDecision:
    """Result of evaluating whether material may enter a vault kind."""

    allowed: bool
    code: VaultDecisionCode
    vault: VaultKind
    content_kind: ContentKind
    classification: DisclosureClassification
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "classification": self.classification.value,
            "code": self.code.value,
            "content_kind": self.content_kind.value,
            "reason": self.reason,
            "vault": self.vault.value,
        }


@dataclass(frozen=True, slots=True)
class QuarantineRecord:
    """Fail-closed quarantine disposition for unknown or mixed material."""

    schema_version: str
    quarantine_id: str
    classification: DisclosureClassification
    reason_codes: tuple[str, ...]
    related_artifact_ids: tuple[str, ...]
    content_kinds: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != PRIVACY_POLICY_SCHEMA_VERSION:
            raise ValueError(
                f"QuarantineRecord.schema_version must be {PRIVACY_POLICY_SCHEMA_VERSION}"
            )
        if not self.quarantine_id or not str(self.quarantine_id).strip():
            raise ValueError("quarantine_id must be non-empty")
        if not self.reason_codes:
            raise ValueError("quarantine requires at least one reason code")

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification.value,
            "content_kinds": list(self.content_kinds),
            "quarantine_id": self.quarantine_id,
            "reason_codes": list(self.reason_codes),
            "related_artifact_ids": list(self.related_artifact_ids),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "QuarantineRecord":
        if not isinstance(value, Mapping):
            raise TypeError("QuarantineRecord must be a mapping")
        return cls(
            schema_version=str(
                value.get("schema_version", PRIVACY_POLICY_SCHEMA_VERSION)
            ),
            quarantine_id=str(value.get("quarantine_id", "")),
            classification=DisclosureClassification(
                str(value.get("classification", DisclosureClassification.UNKNOWN.value))
            ),
            reason_codes=tuple(value.get("reason_codes") or ()),
            related_artifact_ids=tuple(value.get("related_artifact_ids") or ()),
            content_kinds=tuple(value.get("content_kinds") or ()),
        )


# Content kinds that carry private substance and must never enter public sinks
# when classification is non-public.
_SUBSTANTIVE_CONTENT: Final[frozenset[ContentKind]] = frozenset(
    {
        ContentKind.DOCUMENT_BYTES,
        ContentKind.EXTRACTED_TEXT,
        ContentKind.EMBEDDING,
        ContentKind.CONTENT_IDENTIFIER,
        ContentKind.GRAPH_CONTENT,
        ContentKind.CREDENTIAL_SECRET,
    }
)

_ALL_PUBLIC_SINKS: Final[frozenset[PublicSink]] = frozenset(PublicSink)


@dataclass(frozen=True, slots=True)
class UsptoPrivacyPolicy:
    """Versioned fail-closed privacy policy for USPTO domain material.

    External model use over private material is denied by default.
    Credentials vault is never a document store.
    """

    schema_version: str = PRIVACY_POLICY_SCHEMA_VERSION
    allow_external_models_for_private: bool = False
    allow_public_cid_for_private: bool = False
    public_sinks: frozenset[PublicSink] = field(default_factory=lambda: _ALL_PUBLIC_SINKS)

    def __post_init__(self) -> None:
        if self.schema_version != PRIVACY_POLICY_SCHEMA_VERSION:
            raise ValueError(
                f"UsptoPrivacyPolicy.schema_version must be {PRIVACY_POLICY_SCHEMA_VERSION}"
            )
        if not isinstance(self.allow_external_models_for_private, bool):
            raise TypeError("allow_external_models_for_private must be bool")
        if not isinstance(self.allow_public_cid_for_private, bool):
            raise TypeError("allow_public_cid_for_private must be bool")
        sinks = self.public_sinks
        if not isinstance(sinks, frozenset):
            object.__setattr__(self, "public_sinks", frozenset(sinks))
        normalized: set[PublicSink] = set()
        for item in self.public_sinks:
            if isinstance(item, PublicSink):
                normalized.add(item)
            else:
                normalized.add(PublicSink(str(item)))
        object.__setattr__(self, "public_sinks", frozenset(normalized))

    def coerce_classification(
        self, value: DisclosureClassification | str | None
    ) -> DisclosureClassification:
        if value is None:
            return DisclosureClassification.UNKNOWN
        if isinstance(value, DisclosureClassification):
            return value
        try:
            return DisclosureClassification(str(value).strip())
        except ValueError:
            # Unrecognized labels fail closed to quarantine.
            return DisclosureClassification.UNKNOWN

    def classify_before_dispatch(
        self,
        declared: DisclosureClassification | str | None,
        *,
        source_classifications: Sequence[DisclosureClassification | str] = (),
    ) -> DisclosureClassification:
        """Resolve effective classification before any sink or store dispatch.

        Missing/unknown inputs quarantine. Derivatives inherit the most
        restrictive source classification.
        """
        parts: list[DisclosureClassification] = []
        if declared is not None:
            parts.append(self.coerce_classification(declared))
        for item in source_classifications:
            parts.append(self.coerce_classification(item))
        if not parts:
            return DisclosureClassification.UNKNOWN
        return most_restrictive_classification(parts)

    def must_quarantine(
        self, classification: DisclosureClassification | str | None
    ) -> bool:
        return requires_quarantine(self.coerce_classification(classification))

    def quarantine(
        self,
        *,
        quarantine_id: str,
        classification: DisclosureClassification | str | None = None,
        reason_codes: Sequence[str] = ("unknown_classification",),
        related_artifact_ids: Sequence[str] = (),
        content_kinds: Sequence[ContentKind | str] = (),
    ) -> QuarantineRecord:
        cls = self.coerce_classification(classification)
        if not requires_quarantine(cls) and "forced_quarantine" not in reason_codes:
            # Still allow explicit quarantine of known classes when forced.
            cls = DisclosureClassification.UNKNOWN
        kinds = tuple(
            k.value if isinstance(k, ContentKind) else str(k) for k in content_kinds
        )
        return QuarantineRecord(
            schema_version=PRIVACY_POLICY_SCHEMA_VERSION,
            quarantine_id=str(quarantine_id).strip(),
            classification=cls,
            reason_codes=tuple(str(r) for r in reason_codes if str(r).strip()),
            related_artifact_ids=tuple(
                str(a).strip() for a in related_artifact_ids if str(a).strip()
            ),
            content_kinds=kinds,
        )

    def evaluate_sink(
        self,
        classification: DisclosureClassification | str | None,
        sink: PublicSink | str,
        content_kind: ContentKind | str,
    ) -> SinkAdmissionDecision:
        cls = self.coerce_classification(classification)
        sink_enum = sink if isinstance(sink, PublicSink) else PublicSink(str(sink))
        kind = (
            content_kind
            if isinstance(content_kind, ContentKind)
            else ContentKind(str(content_kind))
        )

        if sink_enum not in self.public_sinks:
            return SinkAdmissionDecision(
                allowed=False,
                code=SinkDecisionCode.DENIED_UNKNOWN_SINK,
                classification=cls,
                sink=sink_enum,
                content_kind=kind,
                reason="sink is not a recognized public sink under this policy",
                quarantined=self.must_quarantine(cls),
            )

        if self.must_quarantine(cls):
            return SinkAdmissionDecision(
                allowed=False,
                code=SinkDecisionCode.DENIED_QUARANTINE,
                classification=cls,
                sink=sink_enum,
                content_kind=kind,
                reason="unknown classification is quarantined; public sinks denied",
                quarantined=True,
            )

        if cls is DisclosureClassification.CREDENTIAL_OR_PAYMENT:
            return SinkAdmissionDecision(
                allowed=False,
                code=SinkDecisionCode.DENIED_CREDENTIAL,
                classification=cls,
                sink=sink_enum,
                content_kind=kind,
                reason="credential_or_payment material is prohibited from public sinks",
                quarantined=False,
            )

        if cls is DisclosureClassification.RESTRICTED_EXPORT_REVIEW:
            return SinkAdmissionDecision(
                allowed=False,
                code=SinkDecisionCode.DENIED_EXPORT_REVIEW,
                classification=cls,
                sink=sink_enum,
                content_kind=kind,
                reason="export-review material is denied until human clearance",
                quarantined=False,
            )

        if is_private_classification(cls):
            # Optional override only for non-CID remote prompts is intentionally
            # not provided; external models default denied for private content.
            if (
                sink_enum is PublicSink.REMOTE_PROMPT
                and not self.allow_external_models_for_private
            ):
                return SinkAdmissionDecision(
                    allowed=False,
                    code=SinkDecisionCode.DENIED_PRIVATE,
                    classification=cls,
                    sink=sink_enum,
                    content_kind=kind,
                    reason="external model use over private material is denied by default",
                    quarantined=False,
                )
            if kind is ContentKind.CONTENT_IDENTIFIER and not self.allow_public_cid_for_private:
                return SinkAdmissionDecision(
                    allowed=False,
                    code=SinkDecisionCode.DENIED_PRIVATE,
                    classification=cls,
                    sink=sink_enum,
                    content_kind=kind,
                    reason="private content identifiers must not enter public sinks",
                    quarantined=False,
                )
            if kind in _SUBSTANTIVE_CONTENT:
                return SinkAdmissionDecision(
                    allowed=False,
                    code=SinkDecisionCode.DENIED_PRIVATE,
                    classification=cls,
                    sink=sink_enum,
                    content_kind=kind,
                    reason=(
                        f"private {kind.value} must not enter {sink_enum.value}; "
                        "tenant-isolated private store required"
                    ),
                    quarantined=False,
                )
            # Non-substantive metadata digests of private material still denied
            # on public IPFS/dataset/cache to avoid linking leaks.
            if sink_enum in {
                PublicSink.PUBLIC_IPFS,
                PublicSink.PUBLIC_DATASET,
                PublicSink.PUBLIC_CACHE,
                PublicSink.JUSTICE_DAO,
                PublicSink.TELEMETRY,
                PublicSink.LOGS,
                PublicSink.REMOTE_PROMPT,
            }:
                return SinkAdmissionDecision(
                    allowed=False,
                    code=SinkDecisionCode.DENIED_PRIVATE,
                    classification=cls,
                    sink=sink_enum,
                    content_kind=kind,
                    reason="private-class material denied from all public sinks",
                    quarantined=False,
                )

        if is_public_classification(cls):
            if kind is ContentKind.CREDENTIAL_SECRET:
                return SinkAdmissionDecision(
                    allowed=False,
                    code=SinkDecisionCode.DENIED_CONTENT_KIND,
                    classification=cls,
                    sink=sink_enum,
                    content_kind=kind,
                    reason="credential secrets never enter public sinks",
                    quarantined=False,
                )
            return SinkAdmissionDecision(
                allowed=True,
                code=SinkDecisionCode.ALLOWED,
                classification=cls,
                sink=sink_enum,
                content_kind=kind,
                reason="public classification admitted to public sink",
                quarantined=False,
            )

        # Fail closed for any unhandled classification.
        return SinkAdmissionDecision(
            allowed=False,
            code=SinkDecisionCode.DENIED_QUARANTINE,
            classification=cls,
            sink=sink_enum,
            content_kind=kind,
            reason="unhandled classification fails closed",
            quarantined=True,
        )

    def assert_sink_allowed(
        self,
        classification: DisclosureClassification | str | None,
        sink: PublicSink | str,
        content_kind: ContentKind | str,
    ) -> SinkAdmissionDecision:
        decision = self.evaluate_sink(classification, sink, content_kind)
        if not decision.allowed:
            raise PrivacyBoundaryError(
                decision.reason,
                code=decision.code.value,
                classification=decision.classification.value,
                sink=decision.sink.value,
                content_kind=decision.content_kind.value,
            )
        return decision

    def evaluate_vault(
        self,
        vault: VaultKind | str,
        content_kind: ContentKind | str,
        classification: DisclosureClassification | str | None,
    ) -> VaultAdmissionDecision:
        """Credentials vault is not a document vault (and vice versa)."""
        vault_enum = vault if isinstance(vault, VaultKind) else VaultKind(str(vault))
        kind = (
            content_kind
            if isinstance(content_kind, ContentKind)
            else ContentKind(str(content_kind))
        )
        cls = self.coerce_classification(classification)

        # Unknown classification is retained in the private document vault for
        # human disposition (quarantine), but never treated as public. It must
        # still not enter the credentials vault as a document store.
        if (
            self.must_quarantine(cls)
            and vault_enum is VaultKind.CREDENTIALS
            and kind is not ContentKind.CREDENTIAL_SECRET
        ):
            return VaultAdmissionDecision(
                allowed=False,
                code=VaultDecisionCode.DENIED_QUARANTINE,
                vault=vault_enum,
                content_kind=kind,
                classification=cls,
                reason=(
                    "unknown classification quarantines document material; "
                    "credentials vault is not a document vault"
                ),
            )

        if vault_enum is VaultKind.CREDENTIALS:
            if kind is ContentKind.CREDENTIAL_SECRET:
                return VaultAdmissionDecision(
                    allowed=True,
                    code=VaultDecisionCode.ALLOWED,
                    vault=vault_enum,
                    content_kind=kind,
                    classification=cls,
                    reason="credential secrets belong in the credentials vault",
                )
            if kind in {
                ContentKind.DOCUMENT_BYTES,
                ContentKind.EXTRACTED_TEXT,
                ContentKind.EMBEDDING,
                ContentKind.CONTENT_IDENTIFIER,
                ContentKind.GRAPH_CONTENT,
                ContentKind.METADATA_DIGEST,
            }:
                return VaultAdmissionDecision(
                    allowed=False,
                    code=VaultDecisionCode.DENIED_CREDENTIALS_AS_DOCUMENT,
                    vault=vault_enum,
                    content_kind=kind,
                    classification=cls,
                    reason=(
                        "credentials vault is not a document vault; "
                        f"refuse {kind.value}"
                    ),
                )
            return VaultAdmissionDecision(
                allowed=False,
                code=VaultDecisionCode.DENIED_CLASSIFICATION,
                vault=vault_enum,
                content_kind=kind,
                classification=cls,
                reason="content kind not admissible to credentials vault",
            )

        # Document vault path
        if kind is ContentKind.CREDENTIAL_SECRET:
            return VaultAdmissionDecision(
                allowed=False,
                code=VaultDecisionCode.DENIED_DOCUMENT_AS_CREDENTIAL,
                vault=vault_enum,
                content_kind=kind,
                classification=cls,
                reason="credential secrets must not be stored in the document vault",
            )
        if cls is DisclosureClassification.CREDENTIAL_OR_PAYMENT:
            return VaultAdmissionDecision(
                allowed=False,
                code=VaultDecisionCode.DENIED_CLASSIFICATION,
                vault=vault_enum,
                content_kind=kind,
                classification=cls,
                reason="credential_or_payment is prohibited document-store content",
            )
        if kind in {
            ContentKind.DOCUMENT_BYTES,
            ContentKind.EXTRACTED_TEXT,
            ContentKind.EMBEDDING,
            ContentKind.CONTENT_IDENTIFIER,
            ContentKind.GRAPH_CONTENT,
            ContentKind.METADATA_DIGEST,
        }:
            return VaultAdmissionDecision(
                allowed=True,
                code=VaultDecisionCode.ALLOWED,
                vault=vault_enum,
                content_kind=kind,
                classification=cls,
                reason="document material admitted to document vault",
            )
        return VaultAdmissionDecision(
            allowed=False,
            code=VaultDecisionCode.DENIED_CLASSIFICATION,
            vault=vault_enum,
            content_kind=kind,
            classification=cls,
            reason="content kind not admissible to document vault",
        )

    def assert_vault_allowed(
        self,
        vault: VaultKind | str,
        content_kind: ContentKind | str,
        classification: DisclosureClassification | str | None,
    ) -> VaultAdmissionDecision:
        decision = self.evaluate_vault(vault, content_kind, classification)
        if not decision.allowed:
            raise PrivacyBoundaryError(
                decision.reason,
                code=decision.code.value,
                classification=decision.classification.value,
                content_kind=decision.content_kind.value,
                vault=decision.vault.value,
            )
        return decision

    def redact_for_logs(
        self,
        classification: DisclosureClassification | str | None,
        payload: Mapping[str, Any],
        *,
        allowed_keys: Iterable[str] = ("artifact_id", "matter_id", "classification", "digest"),
    ) -> Mapping[str, Any]:
        """Return a log-safe projection: identifiers/digests only when private.

        Private bytes, text, embeddings, and CIDs are stripped. Audit surfaces
        keep reason codes and digests, never matched private content.
        """
        cls = self.coerce_classification(classification)
        allow = frozenset(str(k) for k in allowed_keys)
        forbidden_value_keys = frozenset(
            {
                "bytes",
                "raw_bytes",
                "text",
                "content",
                "body",
                "embedding",
                "embeddings",
                "vector",
                "vectors",
                "cid",
                "private_cid",
                "content_id",
                "prompt",
                "password",
                "api_key",
                "token",
                "secret",
            }
        )
        out: dict[str, Any] = {"classification": cls.value}
        if is_public_classification(cls) and not self.must_quarantine(cls):
            for key, value in payload.items():
                sk = str(key)
                if sk in forbidden_value_keys:
                    out[sk] = "<redacted>"
                else:
                    out[sk] = value
            return MappingProxyType(out)

        # Private or quarantined: only allowlisted keys; never private substance.
        for key, value in payload.items():
            sk = str(key)
            if sk in forbidden_value_keys:
                continue
            if sk in allow:
                out[sk] = value
        out["redacted"] = True
        return MappingProxyType(out)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_external_models_for_private": self.allow_external_models_for_private,
            "allow_public_cid_for_private": self.allow_public_cid_for_private,
            "public_sinks": sorted(s.value for s in self.public_sinks),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "UsptoPrivacyPolicy":
        if not isinstance(value, Mapping):
            raise TypeError("UsptoPrivacyPolicy must be a mapping")
        sinks_raw = value.get("public_sinks")
        sinks: frozenset[PublicSink]
        if sinks_raw is None:
            sinks = _ALL_PUBLIC_SINKS
        else:
            sinks = frozenset(PublicSink(str(s)) for s in sinks_raw)
        return cls(
            schema_version=str(
                value.get("schema_version", PRIVACY_POLICY_SCHEMA_VERSION)
            ),
            allow_external_models_for_private=bool(
                value.get("allow_external_models_for_private", False)
            ),
            allow_public_cid_for_private=bool(
                value.get("allow_public_cid_for_private", False)
            ),
            public_sinks=sinks,
        )


DEFAULT_PRIVACY_POLICY: Final = UsptoPrivacyPolicy()


def deny_private_to_public_sinks(
    classification: DisclosureClassification | str | None,
    *,
    content_kinds: Sequence[ContentKind | str] | None = None,
    sinks: Sequence[PublicSink | str] | None = None,
    policy: UsptoPrivacyPolicy | None = None,
) -> list[SinkAdmissionDecision]:
    """Evaluate every substantive content kind against every public sink.

    Returns the list of denial decisions. Empty list only when all evaluated
    combinations are allowed (public classification cases).
    """
    pol = policy or DEFAULT_PRIVACY_POLICY
    kinds: Sequence[ContentKind | str] = content_kinds or (
        ContentKind.DOCUMENT_BYTES,
        ContentKind.EXTRACTED_TEXT,
        ContentKind.EMBEDDING,
        ContentKind.CONTENT_IDENTIFIER,
    )
    sink_list: Sequence[PublicSink | str] = sinks or tuple(PublicSink)
    denials: list[SinkAdmissionDecision] = []
    for sink in sink_list:
        for kind in kinds:
            decision = pol.evaluate_sink(classification, sink, kind)
            if not decision.allowed:
                denials.append(decision)
    return denials


__all__ = [
    "DEFAULT_PRIVACY_POLICY",
    "PRIVACY_INTERFACE",
    "PRIVACY_POLICY_SCHEMA_VERSION",
    "ContentKind",
    "PrivacyBoundaryError",
    "PublicSink",
    "QuarantineRecord",
    "SinkAdmissionDecision",
    "SinkDecisionCode",
    "UsptoPrivacyPolicy",
    "VaultAdmissionDecision",
    "VaultDecisionCode",
    "VaultKind",
    "deny_private_to_public_sinks",
    "is_private_classification",
    "is_public_classification",
    "requires_quarantine",
]
