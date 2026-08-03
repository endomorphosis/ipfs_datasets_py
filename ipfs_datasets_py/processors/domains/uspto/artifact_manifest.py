"""Immutable USPTO artifact manifests with privacy-aware CID handling.

An ``ArtifactManifest`` records identity, digests, classification, encryption
namespace, matter linkage, and authoritative/derivative relationships. Private
CIDs are stored only as references for the tenant-isolated private store and
must never be announced to public IPFS, gateways, or pin services.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Mapping, Sequence

from .contracts import (
    CONTRACTS_SCHEMA_VERSION,
    AuthorityRelation,
    DisclosureClassification,
    canonical_json,
    is_private_classification,
    requires_quarantine,
)
from .privacy import (
    ContentKind,
    PrivacyBoundaryError,
    PublicSink,
    UsptoPrivacyPolicy,
    VaultKind,
    DEFAULT_PRIVACY_POLICY,
)

ARTIFACT_MANIFEST_SCHEMA_VERSION: Final = "uspto.artifact-manifest.v1"
ARTIFACT_MANIFEST_INTERFACE: Final = "UsptoArtifactManifest@1"

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
# CIDv0 (Qm...) or CIDv1 (bafy..., bagu..., bafk..., etc.)
_CID_RE = re.compile(r"\A(?:Qm[1-9A-HJ-NP-Za-km-z]{44}|b[a-z2-7]{58,})\Z")


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
    if not isinstance(value, str):
        raise TypeError(f"{field} must be str or None")
    text = value.strip()
    if not text:
        return None
    if len(text) > max_len:
        raise ValueError(f"{field} exceeds max length {max_len}")
    return text


def _identifier(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=256)
    if not _ID_RE.match(text):
        raise ValueError(f"{field} is not a valid identifier: {text!r}")
    return text


def _optional_identifier(value: Any, field: str) -> str | None:
    text = _optional_str(value, field, max_len=256)
    if text is None:
        return None
    if not _ID_RE.match(text):
        raise ValueError(f"{field} is not a valid identifier: {text!r}")
    return text


def _sha256_hex(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64).lower()
    if not _SHA256_RE.match(text):
        raise ValueError(f"{field} must be a 64-char lowercase hex SHA-256 digest")
    return text


def _optional_cid(value: Any, field: str) -> str | None:
    text = _optional_str(value, field, max_len=128)
    if text is None:
        return None
    if not _CID_RE.match(text):
        raise ValueError(f"{field} is not a recognized CID encoding")
    return text


def _nonneg_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be int")
    if value < 0:
        raise ValueError(f"{field} must be >= 0")
    return value


def _coerce_classification(value: Any) -> DisclosureClassification:
    if isinstance(value, DisclosureClassification):
        return value
    if isinstance(value, str):
        try:
            return DisclosureClassification(value.strip())
        except ValueError as exc:
            raise ValueError(f"unknown disclosure classification: {value!r}") from exc
    raise TypeError("classification must be DisclosureClassification or str")


def _coerce_relation(value: Any) -> AuthorityRelation:
    if isinstance(value, AuthorityRelation):
        return value
    if isinstance(value, str):
        try:
            return AuthorityRelation(value.strip())
        except ValueError as exc:
            raise ValueError(f"invalid authority_relation: {value!r}") from exc
    raise TypeError("authority_relation must be AuthorityRelation or str")


def _frozen_str_map(value: Any, field: str, *, max_items: int = 64) -> Mapping[str, str]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    out: dict[str, str] = {}
    for key, raw in value.items():
        k = _require_str(key, f"{field}.key", max_len=128)
        v = _require_str(raw, f"{field}[{k}]", max_len=2048)
        out[k] = v
    return MappingProxyType(dict(sorted(out.items())))


def _tuple_of_str(value: Any, field: str, *, max_items: int = 256) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence of strings")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    return tuple(_require_str(item, f"{field}[{i}]", max_len=256) for i, item in enumerate(value))


@dataclass(frozen=True, slots=True)
class ArtifactManifest:
    """Immutable artifact identity bound to classification and storage namespace.

    Private CIDs reference a separately authorized private network/store. They
    are never valid inputs to public IPFS announcement, public datasets, public
    caches, prompts, logs, or telemetry.
    """

    schema_version: str
    artifact_id: str
    sha256: str
    size_bytes: int
    classification: DisclosureClassification
    media_type: str
    media_signature: str | None
    private_cid: str | None
    public_cid: str | None
    encryption_namespace: str | None
    matter_id: str | None
    source_receipt_id: str | None
    authority_relation: AuthorityRelation
    parent_artifact_ids: tuple[str, ...]
    parser_versions: Mapping[str, str]
    labels: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != ARTIFACT_MANIFEST_SCHEMA_VERSION:
            raise ValueError(
                "ArtifactManifest.schema_version must be "
                f"{ARTIFACT_MANIFEST_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(self, "sha256", _sha256_hex(self.sha256, "sha256"))
        object.__setattr__(
            self, "size_bytes", _nonneg_int(self.size_bytes, "size_bytes")
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        object.__setattr__(
            self, "media_type", _require_str(self.media_type, "media_type", max_len=256)
        )
        object.__setattr__(
            self,
            "media_signature",
            _optional_str(self.media_signature, "media_signature", max_len=256),
        )
        object.__setattr__(
            self, "private_cid", _optional_cid(self.private_cid, "private_cid")
        )
        object.__setattr__(
            self, "public_cid", _optional_cid(self.public_cid, "public_cid")
        )
        object.__setattr__(
            self,
            "encryption_namespace",
            _optional_str(self.encryption_namespace, "encryption_namespace", max_len=256),
        )
        object.__setattr__(
            self, "matter_id", _optional_identifier(self.matter_id, "matter_id")
        )
        object.__setattr__(
            self,
            "source_receipt_id",
            _optional_identifier(self.source_receipt_id, "source_receipt_id"),
        )
        object.__setattr__(
            self,
            "authority_relation",
            _coerce_relation(self.authority_relation),
        )
        object.__setattr__(
            self,
            "parent_artifact_ids",
            _tuple_of_str(self.parent_artifact_ids, "parent_artifact_ids", max_items=64),
        )
        object.__setattr__(
            self,
            "parser_versions",
            _frozen_str_map(self.parser_versions, "parser_versions", max_items=32),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )

        # Invariants: private material cannot carry a public CID.
        if (
            is_private_classification(self.classification)
            or requires_quarantine(self.classification)
        ) and self.public_cid is not None:
            raise ValueError(
                "public_cid is forbidden for private or quarantined classifications"
            )
        if (
            is_private_classification(self.classification)
            or requires_quarantine(self.classification)
        ) and self.encryption_namespace is None:
            raise ValueError(
                "encryption_namespace is required for private or quarantined artifacts"
            )
        if (
            self.classification is DisclosureClassification.CREDENTIAL_OR_PAYMENT
        ):
            raise ValueError(
                "credential_or_payment is prohibited document-store content; "
                "do not create an ArtifactManifest for credentials"
            )

    @property
    def is_quarantined(self) -> bool:
        return requires_quarantine(self.classification)

    @property
    def is_private(self) -> bool:
        return is_private_classification(self.classification)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "authority_relation": self.authority_relation.value,
            "classification": self.classification.value,
            "encryption_namespace": self.encryption_namespace,
            "labels": dict(self.labels),
            "matter_id": self.matter_id,
            "media_signature": self.media_signature,
            "media_type": self.media_type,
            "parent_artifact_ids": list(self.parent_artifact_ids),
            "parser_versions": dict(self.parser_versions),
            "private_cid": self.private_cid,
            "public_cid": self.public_cid,
            "schema_version": self.schema_version,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "source_receipt_id": self.source_receipt_id,
        }

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def public_projection(self) -> dict[str, Any]:
        """Safe projection for public audit surfaces: no private CID or namespace."""
        base = {
            "artifact_id": self.artifact_id,
            "authority_relation": self.authority_relation.value,
            "classification": self.classification.value,
            "media_type": self.media_type,
            "schema_version": self.schema_version,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }
        if self.public_cid is not None and not self.is_private and not self.is_quarantined:
            base["public_cid"] = self.public_cid
        return base

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ArtifactManifest":
        if not isinstance(value, Mapping):
            raise TypeError("ArtifactManifest must be a mapping")
        allowed = frozenset(
            {
                "schema_version",
                "artifact_id",
                "sha256",
                "size_bytes",
                "classification",
                "media_type",
                "media_signature",
                "private_cid",
                "public_cid",
                "encryption_namespace",
                "matter_id",
                "source_receipt_id",
                "authority_relation",
                "parent_artifact_ids",
                "parser_versions",
                "labels",
            }
        )
        extra = sorted(set(value) - allowed)
        if extra:
            raise ValueError(f"ArtifactManifest has unknown fields: {', '.join(extra)}")
        return cls(
            schema_version=value.get(
                "schema_version", ARTIFACT_MANIFEST_SCHEMA_VERSION
            ),
            artifact_id=value.get("artifact_id", ""),
            sha256=value.get("sha256", ""),
            size_bytes=value.get("size_bytes", 0),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            media_type=value.get("media_type", "application/octet-stream"),
            media_signature=value.get("media_signature"),
            private_cid=value.get("private_cid"),
            public_cid=value.get("public_cid"),
            encryption_namespace=value.get("encryption_namespace"),
            matter_id=value.get("matter_id"),
            source_receipt_id=value.get("source_receipt_id"),
            authority_relation=value.get(
                "authority_relation", AuthorityRelation.UNKNOWN.value
            ),
            parent_artifact_ids=tuple(value.get("parent_artifact_ids") or ()),
            parser_versions=value.get("parser_versions") or {},
            labels=value.get("labels") or {},
        )

    def assert_not_public_sink(
        self,
        sink: PublicSink | str,
        content_kind: ContentKind | str,
        *,
        policy: UsptoPrivacyPolicy | None = None,
    ) -> None:
        """Raise if this artifact's material may not enter *sink*."""
        pol = policy or DEFAULT_PRIVACY_POLICY
        pol.assert_sink_allowed(self.classification, sink, content_kind)

    def assert_document_vault_only(
        self, *, policy: UsptoPrivacyPolicy | None = None
    ) -> None:
        """Document artifacts use the document vault, never the credentials vault."""
        pol = policy or DEFAULT_PRIVACY_POLICY
        pol.assert_vault_allowed(
            VaultKind.DOCUMENT,
            ContentKind.DOCUMENT_BYTES,
            self.classification,
        )
        denied = pol.evaluate_vault(
            VaultKind.CREDENTIALS,
            ContentKind.DOCUMENT_BYTES,
            self.classification,
        )
        if denied.allowed:
            raise PrivacyBoundaryError(
                "credentials vault accepted document bytes (policy misconfiguration)",
                code="denied_credentials_vault_document_store",
                classification=self.classification.value,
                content_kind=ContentKind.DOCUMENT_BYTES.value,
                vault=VaultKind.CREDENTIALS.value,
            )

    def private_cid_public_sink_denials(
        self, *, policy: UsptoPrivacyPolicy | None = None
    ) -> list[dict[str, Any]]:
        """Prove private CIDs cannot enter any public sink."""
        if self.private_cid is None:
            return []
        pol = policy or DEFAULT_PRIVACY_POLICY
        denials: list[dict[str, Any]] = []
        for sink in PublicSink:
            decision = pol.evaluate_sink(
                self.classification, sink, ContentKind.CONTENT_IDENTIFIER
            )
            if not decision.allowed:
                denials.append(decision.to_dict())
        return denials


def build_artifact_manifest(
    *,
    artifact_id: str,
    sha256: str,
    size_bytes: int,
    classification: DisclosureClassification | str,
    media_type: str = "application/octet-stream",
    media_signature: str | None = None,
    private_cid: str | None = None,
    public_cid: str | None = None,
    encryption_namespace: str | None = None,
    matter_id: str | None = None,
    source_receipt_id: str | None = None,
    authority_relation: AuthorityRelation | str = AuthorityRelation.AUTHORITATIVE_ORIGINAL,
    parent_artifact_ids: Sequence[str] = (),
    parser_versions: Mapping[str, str] | None = None,
    labels: Mapping[str, str] | None = None,
    policy: UsptoPrivacyPolicy | None = None,
) -> ArtifactManifest:
    """Construct a manifest after privacy gate checks.

    Unknown classification is allowed only as a quarantined private-store
    record (encryption namespace required). Credential classification is
    refused entirely.
    """
    pol = policy or DEFAULT_PRIVACY_POLICY
    cls = pol.coerce_classification(classification)
    if cls is DisclosureClassification.CREDENTIAL_OR_PAYMENT:
        raise PrivacyBoundaryError(
            "credential_or_payment must not become a document ArtifactManifest",
            code="denied_classification",
            classification=cls.value,
            content_kind=ContentKind.DOCUMENT_BYTES.value,
            vault=VaultKind.DOCUMENT.value,
        )
    if requires_quarantine(cls) or is_private_classification(cls):
        if encryption_namespace is None:
            encryption_namespace = f"private://tenant/uspto/{artifact_id}"
        if public_cid is not None:
            raise PrivacyBoundaryError(
                "public_cid forbidden for private/quarantined artifacts",
                code="denied_private",
                classification=cls.value,
                sink=PublicSink.PUBLIC_IPFS.value,
                content_kind=ContentKind.CONTENT_IDENTIFIER.value,
            )
    manifest = ArtifactManifest(
        schema_version=ARTIFACT_MANIFEST_SCHEMA_VERSION,
        artifact_id=artifact_id,
        sha256=sha256,
        size_bytes=size_bytes,
        classification=cls,
        media_type=media_type,
        media_signature=media_signature,
        private_cid=private_cid,
        public_cid=public_cid,
        encryption_namespace=encryption_namespace,
        matter_id=matter_id,
        source_receipt_id=source_receipt_id,
        authority_relation=authority_relation,
        parent_artifact_ids=tuple(parent_artifact_ids),
        parser_versions=dict(parser_versions or {}),
        labels=dict(labels or {}),
    )
    # Document material never lands in the credentials vault.
    manifest.assert_document_vault_only(policy=pol)
    return manifest


__all__ = [
    "ARTIFACT_MANIFEST_INTERFACE",
    "ARTIFACT_MANIFEST_SCHEMA_VERSION",
    "ArtifactManifest",
    "CONTRACTS_SCHEMA_VERSION",
    "build_artifact_manifest",
]
