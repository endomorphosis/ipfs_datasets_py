"""Versioned schemas for the family-agnostic proof corpus store.

The proof corpus unifies Intent, Legal, and Security formal artifacts into one
content-addressed envelope surface (ProofCorpusStore@1 / LIG-G050).  Envelopes
are authoritative; secondary indexes (LIG-012) rebuild from them.

Wire contracts in this module:

* ``proof-corpus-envelope/v1`` — immutable envelope for one stored artifact
* ``proof-corpus-store/v1`` — store configuration / identity constants
* ``proof-corpus-index/v1`` — on-disk secondary index shape used by the store

Integrity is fail-closed: digest/CID drift, unknown families, and unknown
schema versions raise typed errors and never load as valid envelopes.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Final

from ..formalization.compiler import FormalizationArtifact
from ..ir_core.identity import cid_v1_from_digest


PROOF_CORPUS_STORE_INTERFACE: Final = "ProofCorpusStore@1"
PROOF_CORPUS_STORE_SCHEMA_VERSION: Final = "proof-corpus-store/v1"
PROOF_CORPUS_ENVELOPE_SCHEMA_VERSION: Final = "proof-corpus-envelope/v1"
PROOF_CORPUS_INDEX_SCHEMA_VERSION: Final = "proof-corpus-index/v1"

# Closed set of IR families the unified store accepts (plan §2.2 / LIG-G050).
PROOF_CORPUS_FAMILY_VALUES: Final[tuple[str, ...]] = (
    "intent",
    "legal",
    "security",
)

_PROFILE_RE: Final = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_DIGEST_RE: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_REVIEW_STATE_RE: Final = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

_ENVELOPE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "artifact",
        "artifact_cid",
        "artifact_digest",
        "attachments",
        "content_cid",
        "content_digest",
        "family",
        "jurisdiction",
        "profile",
        "producer_id",
        "review_state",
        "schema_version",
        "source_digest",
        "source_id",
    }
)

_ATTACHMENT_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "declaration",
        "declaration_cid",
        "declaration_digest",
        "extension_ids",
        "extension_vocabularies",
        "policy_decisions",
        "theorem_receipts",
    }
)


class ProofCorpusSchemaError(ValueError):
    """Raised when a proof-corpus schema value is malformed or unsupported."""


class ProofCorpusIntegrityError(ProofCorpusSchemaError):
    """Raised when an envelope fails integrity rehash or family binding checks."""


class ProofCorpusFamily(str, Enum):
    """Closed IR family vocabulary accepted by the proof corpus store."""

    INTENT = "intent"
    LEGAL = "legal"
    SECURITY = "security"


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ProofCorpusSchemaError(
            f"{field_name} must be a non-empty trimmed string"
        )
    return value


def _require_profile(value: Any) -> str:
    profile = _require_text(value, "profile")
    if not _PROFILE_RE.fullmatch(profile):
        raise ProofCorpusSchemaError(
            "profile must be a lowercase hyphenated identifier"
        )
    return profile


def _require_digest(value: Any, field_name: str) -> str:
    digest = _require_text(value, field_name)
    if not _DIGEST_RE.fullmatch(digest):
        raise ProofCorpusSchemaError(
            f"{field_name} must be a sha256:<hex> digest"
        )
    return digest


def _require_review_state(value: Any) -> str:
    state = _require_text(value, "review_state")
    if not _REVIEW_STATE_RE.fullmatch(state):
        raise ProofCorpusSchemaError(
            "review_state must be a lowercase identifier (letters, digits, _)"
        )
    return state


def as_mapping(value: Any, label: str) -> Mapping[str, Any]:
    """Require a mapping value (public helper for store/index modules)."""

    if not isinstance(value, Mapping):
        raise ProofCorpusSchemaError(f"{label} must be a mapping")
    return value


# Backward-compatible private alias used within this module.
_as_mapping = as_mapping


def canonical_bytes(value: Any) -> bytes:
    """Canonical JSON bytes used for envelope identity digests."""

    return _canonical_bytes(value)


def require_text(value: Any, field_name: str) -> str:
    """Public trimmed non-empty string validator."""

    return _require_text(value, field_name)


def require_digest(value: Any, field_name: str) -> str:
    """Public sha256:<hex> digest validator."""

    return _require_digest(value, field_name)


def require_profile(value: Any) -> str:
    """Public profile identifier validator."""

    return _require_profile(value)


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_ready(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    raise ProofCorpusSchemaError(
        f"value of type {type(value).__name__} is not JSON-serializable "
        "for the proof corpus"
    )


def parse_family(value: Any) -> ProofCorpusFamily:
    """Parse a closed-vocabulary family wire value (fail closed on unknown)."""

    if isinstance(value, ProofCorpusFamily):
        return value
    text = _require_text(value, "family")
    try:
        return ProofCorpusFamily(text)
    except ValueError as exc:
        raise ProofCorpusSchemaError(
            f"unknown proof corpus family {text!r}; "
            f"allowed: {', '.join(PROOF_CORPUS_FAMILY_VALUES)}"
        ) from exc


def family_for_domain(domain: str) -> ProofCorpusFamily:
    """Map a formalization artifact domain onto a proof-corpus family."""

    domain = _require_text(domain, "domain")
    try:
        return ProofCorpusFamily(domain)
    except ValueError as exc:
        raise ProofCorpusSchemaError(
            f"formalization domain {domain!r} is not a proof-corpus family"
        ) from exc


def normalize_artifact(
    artifact: FormalizationArtifact | Mapping[str, Any],
    *,
    expected_family: ProofCorpusFamily | None = None,
) -> tuple[FormalizationArtifact, dict[str, Any]]:
    """Validate and re-serialize a formalization artifact for storage."""

    if isinstance(artifact, FormalizationArtifact):
        produced = artifact
    else:
        try:
            produced = FormalizationArtifact.from_dict(
                _as_mapping(artifact, "artifact")
            )
        except (TypeError, ValueError) as exc:
            raise ProofCorpusSchemaError(
                f"invalid formalization artifact: {exc}"
            ) from exc
    family = family_for_domain(produced.domain)
    if expected_family is not None and family is not expected_family:
        raise ProofCorpusIntegrityError(
            f"artifact domain {produced.domain!r} does not match envelope "
            f"family {expected_family.value!r}"
        )
    return produced, produced.to_dict()


def normalize_attachments(value: Any) -> dict[str, Any]:
    """Normalize optional family-specific attachments (fail closed on unknown)."""

    if value is None:
        return {}
    payload = dict(_as_mapping(value, "attachments"))
    unknown = sorted(set(payload) - _ATTACHMENT_FIELDS)
    if unknown:
        raise ProofCorpusSchemaError(
            "unknown attachment field(s): " + ", ".join(unknown)
        )
    out: dict[str, Any] = {}
    if "theorem_receipts" in payload:
        receipts = payload["theorem_receipts"]
        if not isinstance(receipts, Sequence) or isinstance(
            receipts, (str, bytes, bytearray)
        ):
            raise ProofCorpusSchemaError(
                "attachments.theorem_receipts must be a sequence"
            )
        out["theorem_receipts"] = [
            _json_ready(dict(_as_mapping(item, "theorem_receipt")))
            for item in receipts
        ]
    if "policy_decisions" in payload:
        decisions = payload["policy_decisions"]
        if not isinstance(decisions, Sequence) or isinstance(
            decisions, (str, bytes, bytearray)
        ):
            raise ProofCorpusSchemaError(
                "attachments.policy_decisions must be a sequence"
            )
        out["policy_decisions"] = [
            _json_ready(dict(_as_mapping(item, "policy_decision")))
            for item in decisions
        ]
    if "declaration" in payload:
        out["declaration"] = _json_ready(
            dict(_as_mapping(payload["declaration"], "declaration"))
        )
    if "declaration_cid" in payload and payload["declaration_cid"] not in (
        None,
        "",
    ):
        out["declaration_cid"] = _require_text(
            payload["declaration_cid"], "attachments.declaration_cid"
        )
    if "declaration_digest" in payload and payload["declaration_digest"] not in (
        None,
        "",
    ):
        out["declaration_digest"] = _require_digest(
            payload["declaration_digest"], "attachments.declaration_digest"
        )
    if "extension_ids" in payload:
        ids = payload["extension_ids"]
        if not isinstance(ids, Sequence) or isinstance(ids, (str, bytes, bytearray)):
            raise ProofCorpusSchemaError(
                "attachments.extension_ids must be a sequence of strings"
            )
        normalized_ids = [
            _require_text(item, "attachments.extension_ids") for item in ids
        ]
        if len(normalized_ids) != len(set(normalized_ids)):
            raise ProofCorpusSchemaError(
                "attachments.extension_ids must be unique"
            )
        out["extension_ids"] = sorted(normalized_ids)
    if "extension_vocabularies" in payload:
        vocabs = payload["extension_vocabularies"]
        if not isinstance(vocabs, Sequence) or isinstance(
            vocabs, (str, bytes, bytearray)
        ):
            raise ProofCorpusSchemaError(
                "attachments.extension_vocabularies must be a sequence of strings"
            )
        normalized_vocabs = [
            _require_text(item, "attachments.extension_vocabularies")
            for item in vocabs
        ]
        if len(normalized_vocabs) != len(set(normalized_vocabs)):
            raise ProofCorpusSchemaError(
                "attachments.extension_vocabularies must be unique"
            )
        out["extension_vocabularies"] = sorted(normalized_vocabs)
    return out


@dataclass(frozen=True, slots=True)
class ArtifactEnvelope:
    """One content-addressed proof-corpus envelope (schema + artifact + meta).

    Envelopes bind a formalization artifact to a family, source identity,
    profile, optional family attachments, and a recomputed content digest/CID.
    Load paths rehash identity and fail closed on drift.
    """

    family: ProofCorpusFamily
    source_id: str
    source_digest: str
    profile: str
    artifact: Mapping[str, Any]
    artifact_digest: str = ""
    artifact_cid: str = ""
    attachments: Mapping[str, Any] = MappingProxyType({})
    producer_id: str = ""
    review_state: str = "reviewed"
    jurisdiction: str = ""
    content_digest: str = ""
    content_cid: str = ""
    schema_version: str = PROOF_CORPUS_ENVELOPE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        family = parse_family(self.family)
        object.__setattr__(self, "family", family)
        object.__setattr__(
            self, "source_id", _require_text(self.source_id, "source_id")
        )
        object.__setattr__(
            self,
            "source_digest",
            _require_digest(self.source_digest, "source_digest"),
        )
        object.__setattr__(self, "profile", _require_profile(self.profile))
        object.__setattr__(
            self, "review_state", _require_review_state(self.review_state)
        )
        if self.jurisdiction not in ("", None):
            jurisdiction = _require_text(self.jurisdiction, "jurisdiction")
            if not _PROFILE_RE.fullmatch(jurisdiction):
                raise ProofCorpusSchemaError(
                    "jurisdiction must be a lowercase hyphenated identifier"
                )
            object.__setattr__(self, "jurisdiction", jurisdiction)
        else:
            object.__setattr__(self, "jurisdiction", "")

        if self.producer_id not in ("", None):
            object.__setattr__(
                self, "producer_id", _require_text(self.producer_id, "producer_id")
            )
        else:
            object.__setattr__(self, "producer_id", "")

        if self.schema_version != PROOF_CORPUS_ENVELOPE_SCHEMA_VERSION:
            raise ProofCorpusSchemaError(
                f"unsupported proof corpus envelope schema: {self.schema_version!r}"
            )

        produced, artifact_payload = normalize_artifact(
            dict(_as_mapping(self.artifact, "artifact")),
            expected_family=family,
        )
        object.__setattr__(self, "artifact", MappingProxyType(artifact_payload))
        art_digest = produced.digest
        art_cid = produced.artifact_id
        if self.artifact_digest:
            recorded = _require_digest(self.artifact_digest, "artifact_digest")
            if recorded != art_digest:
                raise ProofCorpusIntegrityError(
                    "artifact_digest does not match recomputed formalization identity"
                )
        if self.artifact_cid:
            recorded_cid = _require_text(self.artifact_cid, "artifact_cid")
            if recorded_cid != art_cid:
                raise ProofCorpusIntegrityError(
                    "artifact_cid does not match recomputed formalization identity"
                )
        object.__setattr__(self, "artifact_digest", art_digest)
        object.__setattr__(self, "artifact_cid", art_cid)

        if produced.declaration_digest != self.source_digest:
            raise ProofCorpusIntegrityError(
                "source_digest does not match artifact declaration_digest"
            )
        if self.source_id not in {produced.declaration_id, produced.sample_id}:
            raise ProofCorpusIntegrityError(
                "source_id does not match artifact declaration_id or sample_id"
            )

        attachments = normalize_attachments(self.attachments)
        object.__setattr__(self, "attachments", MappingProxyType(attachments))
        self._validate_family_attachments(produced)

        body = self._identity_payload()
        digest = _sha256_digest(_canonical_bytes(body))
        cid = cid_v1_from_digest(bytes.fromhex(digest.removeprefix("sha256:")))
        if self.content_digest:
            recorded = _require_digest(self.content_digest, "content_digest")
            if recorded != digest:
                raise ProofCorpusIntegrityError(
                    "envelope content_digest does not match payload"
                )
        if self.content_cid:
            recorded_cid = _require_text(self.content_cid, "content_cid")
            if recorded_cid != cid:
                raise ProofCorpusIntegrityError(
                    "envelope content_cid does not match payload"
                )
        object.__setattr__(self, "content_digest", digest)
        object.__setattr__(self, "content_cid", cid)

        self.verify_integrity()

    def _validate_family_attachments(
        self, artifact: FormalizationArtifact
    ) -> None:
        """Enforce family-specific attachment rules (fail closed)."""

        attachments = dict(self.attachments)
        if self.family is ProofCorpusFamily.LEGAL:
            # theorem_receipts optional; security-only fields forbidden
            for forbidden in (
                "declaration",
                "declaration_cid",
                "declaration_digest",
                "policy_decisions",
                "extension_ids",
                "extension_vocabularies",
            ):
                if forbidden in attachments:
                    raise ProofCorpusSchemaError(
                        f"legal envelope must not carry attachments.{forbidden}"
                    )
        elif self.family is ProofCorpusFamily.SECURITY:
            for forbidden in ("theorem_receipts",):
                if forbidden in attachments:
                    raise ProofCorpusSchemaError(
                        f"security envelope must not carry attachments.{forbidden}"
                    )
            declaration = attachments.get("declaration")
            if declaration is not None:
                decl_digest = attachments.get("declaration_digest")
                if decl_digest and decl_digest != artifact.declaration_digest:
                    raise ProofCorpusIntegrityError(
                        "attachments.declaration_digest does not match "
                        "artifact declaration_digest"
                    )
        elif self.family is ProofCorpusFamily.INTENT:
            # Intent fixtures are formalization artifacts only; no attachments.
            if attachments:
                raise ProofCorpusSchemaError(
                    "intent envelope must not carry family-specific attachments"
                )

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "artifact": _json_ready(dict(self.artifact)),
            "artifact_cid": self.artifact_cid,
            "artifact_digest": self.artifact_digest,
            "attachments": _json_ready(dict(self.attachments)),
            "family": self.family.value,
            "jurisdiction": self.jurisdiction,
            "producer_id": self.producer_id,
            "profile": self.profile,
            "review_state": self.review_state,
            "schema_version": self.schema_version,
            "source_digest": self.source_digest,
            "source_id": self.source_id,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._identity_payload()
        payload["content_cid"] = self.content_cid
        payload["content_digest"] = self.content_digest
        return payload

    def formalization_artifact(self) -> FormalizationArtifact:
        """Return the stored formalization artifact (revalidated)."""

        try:
            return FormalizationArtifact.from_dict(dict(self.artifact))
        except (TypeError, ValueError) as exc:
            raise ProofCorpusIntegrityError(
                f"stored artifact is not a valid FormalizationArtifact: {exc}"
            ) from exc

    def verify_integrity(self) -> "ArtifactEnvelope":
        """Recompute artifact identity and family bindings; fail closed on drift."""

        artifact = self.formalization_artifact()
        family = family_for_domain(artifact.domain)
        if family is not self.family:
            raise ProofCorpusIntegrityError(
                f"stored artifact domain {artifact.domain!r} drifted from "
                f"envelope family {self.family.value!r}"
            )
        if artifact.digest != self.artifact_digest:
            raise ProofCorpusIntegrityError(
                "stored artifact_digest does not match recomputed identity"
            )
        if artifact.artifact_id != self.artifact_cid:
            raise ProofCorpusIntegrityError(
                "stored artifact_cid does not match recomputed identity"
            )
        if artifact.declaration_digest != self.source_digest:
            raise ProofCorpusIntegrityError(
                "source_digest drifted from artifact declaration_digest"
            )
        if self.source_id not in {artifact.declaration_id, artifact.sample_id}:
            raise ProofCorpusIntegrityError(
                "source_id drifted from artifact declaration/sample identity"
            )
        self._validate_family_attachments(artifact)
        body = self._identity_payload()
        digest = _sha256_digest(_canonical_bytes(body))
        if digest != self.content_digest:
            raise ProofCorpusIntegrityError(
                "envelope content_digest drifted from recomputed payload"
            )
        cid = cid_v1_from_digest(bytes.fromhex(digest.removeprefix("sha256:")))
        if cid != self.content_cid:
            raise ProofCorpusIntegrityError(
                "envelope content_cid drifted from recomputed payload"
            )
        return self

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ArtifactEnvelope":
        value = _as_mapping(value, "artifact envelope")
        unknown = sorted(set(value) - _ENVELOPE_FIELDS)
        if unknown:
            raise ProofCorpusSchemaError(
                "unknown artifact envelope field(s): " + ", ".join(unknown)
            )
        return cls(
            family=value.get("family", ""),
            source_id=value.get("source_id", ""),
            source_digest=value.get("source_digest", ""),
            profile=value.get("profile", ""),
            artifact=value.get("artifact", {}),
            artifact_digest=value.get("artifact_digest", ""),
            artifact_cid=value.get("artifact_cid", ""),
            attachments=value.get("attachments", {}) or {},
            producer_id=value.get("producer_id", "") or "",
            review_state=value.get("review_state", "reviewed") or "reviewed",
            jurisdiction=value.get("jurisdiction", "") or "",
            content_digest=value.get("content_digest", ""),
            content_cid=value.get("content_cid", ""),
            schema_version=value.get(
                "schema_version", PROOF_CORPUS_ENVELOPE_SCHEMA_VERSION
            ),
        )

    @classmethod
    def build(
        cls,
        artifact: FormalizationArtifact | Mapping[str, Any],
        *,
        profile: str,
        family: ProofCorpusFamily | str | None = None,
        source_id: str | None = None,
        source_digest: str | None = None,
        attachments: Mapping[str, Any] | None = None,
        producer_id: str = "",
        review_state: str = "reviewed",
        jurisdiction: str = "",
    ) -> "ArtifactEnvelope":
        """Build a verified envelope from a formalization artifact."""

        expected = parse_family(family) if family is not None else None
        produced, artifact_payload = normalize_artifact(
            artifact, expected_family=expected
        )
        resolved_family = expected or family_for_domain(produced.domain)
        resolved_source_id = source_id or produced.declaration_id or produced.sample_id
        resolved_source_digest = source_digest or produced.declaration_digest
        if source_digest is not None:
            resolved_source_digest = _require_digest(source_digest, "source_digest")
            if resolved_source_digest != produced.declaration_digest:
                raise ProofCorpusSchemaError(
                    "source_digest does not match artifact declaration_digest"
                )
        return cls(
            family=resolved_family,
            source_id=_require_text(resolved_source_id, "source_id"),
            source_digest=_require_digest(
                resolved_source_digest, "source_digest"
            ),
            profile=_require_profile(profile),
            artifact=artifact_payload,
            artifact_digest=produced.digest,
            artifact_cid=produced.artifact_id,
            attachments=attachments or {},
            producer_id=producer_id or "",
            review_state=review_state,
            jurisdiction=jurisdiction or "",
        )

    @classmethod
    def from_intent_artifact(
        cls,
        artifact: FormalizationArtifact | Mapping[str, Any],
        *,
        profile: str,
        producer_id: str = "intent-formalization",
        review_state: str = "reviewed",
    ) -> "ArtifactEnvelope":
        """Wrap an Intent formalization fixture as a proof-corpus envelope."""

        return cls.build(
            artifact,
            profile=profile,
            family=ProofCorpusFamily.INTENT,
            producer_id=producer_id,
            review_state=review_state,
        )

    @classmethod
    def from_legal_record(
        cls,
        record: Mapping[str, Any],
        *,
        producer_id: str = "legal-proof-cache",
        review_state: str = "reviewed",
    ) -> "ArtifactEnvelope":
        """Adapt a LegalProofCache record mapping into a unified envelope.

        Family cache records remain sources of fixtures; this adapter does not
        import the legal cache module so the proof corpus package stays free of
        family-cache dependencies.
        """

        payload = dict(_as_mapping(record, "legal proof record"))
        artifact = payload.get("artifact", {})
        attachments: dict[str, Any] = {}
        if payload.get("theorem_receipts"):
            attachments["theorem_receipts"] = list(payload["theorem_receipts"])
        return cls.build(
            artifact,
            profile=payload.get("profile", ""),
            family=ProofCorpusFamily.LEGAL,
            source_id=payload.get("source_id"),
            source_digest=payload.get("source_digest"),
            attachments=attachments,
            producer_id=producer_id,
            review_state=review_state,
            jurisdiction=payload.get("jurisdiction", "") or "",
        )

    @classmethod
    def from_security_record(
        cls,
        record: Mapping[str, Any],
        *,
        producer_id: str = "security-constraint-cache",
        review_state: str = "reviewed",
    ) -> "ArtifactEnvelope":
        """Adapt a SecurityConstraintCache record mapping into a unified envelope."""

        payload = dict(_as_mapping(record, "security constraint record"))
        artifact = payload.get("artifact", {})
        attachments: dict[str, Any] = {}
        if "declaration" in payload:
            attachments["declaration"] = payload["declaration"]
        if payload.get("declaration_cid"):
            attachments["declaration_cid"] = payload["declaration_cid"]
        if payload.get("declaration_digest"):
            attachments["declaration_digest"] = payload["declaration_digest"]
        if payload.get("policy_decisions"):
            attachments["policy_decisions"] = list(payload["policy_decisions"])
        if payload.get("extension_ids"):
            attachments["extension_ids"] = list(payload["extension_ids"])
        if payload.get("extension_vocabularies"):
            attachments["extension_vocabularies"] = list(
                payload["extension_vocabularies"]
            )
        source_id = payload.get("declaration_id") or payload.get("source_id")
        source_digest = payload.get("declaration_digest") or payload.get(
            "source_digest"
        )
        return cls.build(
            artifact,
            profile=payload.get("profile", ""),
            family=ProofCorpusFamily.SECURITY,
            source_id=source_id,
            source_digest=source_digest,
            attachments=attachments,
            producer_id=producer_id,
            review_state=review_state,
        )


def envelope_identity_digest(envelope: ArtifactEnvelope | Mapping[str, Any]) -> str:
    """Return the content digest for an envelope without requiring a typed value."""

    if isinstance(envelope, ArtifactEnvelope):
        return envelope.content_digest
    return ArtifactEnvelope.from_dict(envelope).content_digest


__all__ = [
    "PROOF_CORPUS_ENVELOPE_SCHEMA_VERSION",
    "PROOF_CORPUS_FAMILY_VALUES",
    "PROOF_CORPUS_INDEX_SCHEMA_VERSION",
    "PROOF_CORPUS_STORE_INTERFACE",
    "PROOF_CORPUS_STORE_SCHEMA_VERSION",
    "ArtifactEnvelope",
    "ProofCorpusFamily",
    "ProofCorpusIntegrityError",
    "ProofCorpusSchemaError",
    "as_mapping",
    "canonical_bytes",
    "envelope_identity_digest",
    "family_for_domain",
    "normalize_artifact",
    "normalize_attachments",
    "parse_family",
    "require_digest",
    "require_profile",
    "require_text",
]
