"""CanonicalProofCacheKey@1 — datasets-owned semantic cache-key contract.

Interface generation: ``CanonicalProofCacheKey@1`` (LPC-080 / LPC-G080).

Every cache identity binds the closed set of semantic fields that can change a
proof outcome.  Datasets owns these semantics; the supervisor may own placement
and single-flight only and must not redefine meaning.

Construction and admission are fail-closed:

* missing identity fields are rejected;
* empty digests are rejected;
* CID-looking strings that are not structurally valid CIDv1 are rejected;
* default-string unknown placeholders are rejected;
* candidate-as-kernel pairings (candidate evidence kind + kernel-grade
  authority ceiling) are rejected;
* cross-environment hits are rejected on lookup admission.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from ipfs_datasets_py.logic.ir_core.axes import (
    LogicEvidenceAuthority,
    LogicEvidenceKind,
)
from ipfs_datasets_py.logic.ir_core.identity import (
    CID_VERSION,
    DIGEST_SIZE,
    MULTIHASH_CODE,
    cid_v1,
    sha256_digest,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

CANONICAL_PROOF_CACHE_KEY_INTERFACE: Final = "CanonicalProofCacheKey@1"
CANONICAL_PROOF_CACHE_KEY_GENERATION: Final = "CanonicalProofCacheKey@1"
CANONICAL_PROOF_CACHE_KEY_MODULE_VERSION: Final = "1.0.0"
CANONICAL_PROOF_CACHE_KEY_SCHEMA: Final = (
    "ipfs_datasets_py/canonical-proof-cache-key@1"
)
CANONICAL_PROOF_CACHE_KEY_SCHEMA_VERSION: Final = "canonical-proof-cache-key/v1"

# Closed inventory of semantic identity fields required on every key body.
# Matches LPC-G080 acceptance: source, expression, formalization, slice,
# obligation, assumptions, bounds, translation, provider, environment, policy,
# schema, checker, network policy, evidence kind, and authority ceiling.
REQUIRED_IDENTITY_FIELDS: Final[tuple[str, ...]] = (
    "source",
    "expression",
    "formalization",
    "slice",
    "obligation",
    "assumptions",
    "bounds",
    "translation",
    "provider",
    "environment",
    "policy",
    "schema",
    "checker",
    "network_policy",
    "evidence_kind",
    "authority_ceiling",
)

# Digest-bound dimensions (must be ``sha256:<64 lowercase hex>``).
_DIGEST_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "source",
        "expression",
        "formalization",
        "slice",
        "obligation",
        "assumptions",
        "bounds",
        "translation",
        "environment",
        "policy",
        "schema",
        "network_policy",
    }
)

# Stable non-digest identifiers (provider / checker product ids).
_STABLE_ID_FIELDS: Final[frozenset[str]] = frozenset({"provider", "checker"})

_DIGEST_RE: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_BARE_DIGEST_RE: Final = re.compile(r"^[0-9a-f]{64}$")
# Multibase base32 CIDv1 text form: leading ``b`` + lowercase RFC4648 alphabet.
_CID_LOOKING_RE: Final = re.compile(r"^b[a-z2-7]{10,200}$")
# Synthetic HF-style cache keys and other CID-shaped impostors often mix hex.
_CID_IMPOSTOR_RE: Final = re.compile(
    r"^(?:bafy|bafk|bafz|bagu|Qm)[0-9a-zA-Z]{8,}$"
)
_DEFAULT_UNKNOWN_PLACEHOLDERS: Final[frozenset[str]] = frozenset(
    {
        "unknown",
        "<unknown>",
        "none",
        "null",
        "nil",
        "n/a",
        "na",
        "undefined",
        "default",
        "unspecified",
        "todo",
        "tbd",
        "placeholder",
        "?",
        "...",
    }
)

# Evidence kinds that describe candidates / non-proof formats only.
_CANDIDATE_EVIDENCE_KINDS: Final[frozenset[LogicEvidenceKind]] = frozenset(
    {
        LogicEvidenceKind.CANDIDATE,
        LogicEvidenceKind.ATP_CANDIDATE,
        LogicEvidenceKind.SMT_CANDIDATE,
        LogicEvidenceKind.LLM_OUTPUT,
        LogicEvidenceKind.MODEL_OUTPUT,
        LogicEvidenceKind.DECLARATION,
        LogicEvidenceKind.REVIEW,
    }
)

# Authority ceilings that may accompany kernel / theorem admission.
_KERNEL_GRADE_AUTHORITY: Final[frozenset[LogicEvidenceAuthority]] = frozenset(
    {
        LogicEvidenceAuthority.AUTHORITATIVE,
        LogicEvidenceAuthority.INDEPENDENTLY_CHECKABLE,
    }
)


class CanonicalCacheKeyError(ValueError):
    """Raised when a canonical proof cache key is malformed or inadmissible."""


class CandidateAsKernelError(CanonicalCacheKeyError):
    """Raised when candidate evidence claims kernel-grade authority."""


class CrossEnvironmentHitError(CanonicalCacheKeyError):
    """Raised when a cache hit spans mismatched environment identities."""


class InvalidCidError(CanonicalCacheKeyError):
    """Raised when a CID-looking value is not a structurally valid CIDv1."""


class EmptyDigestError(CanonicalCacheKeyError):
    """Raised when a required digest is empty or blank."""


# ---------------------------------------------------------------------------
# Low-level validators
# ---------------------------------------------------------------------------


def _varint_read(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        if offset >= len(data):
            raise InvalidCidError("truncated CIDv1 multiformat stream")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7
        if shift > 63:
            raise InvalidCidError("CIDv1 varint overflow")


def _base32_decode_cid_body(body: str) -> bytes:
    """Decode lowercase unpadded base32 multibase body to raw bytes."""

    if not body or any(ch not in "abcdefghijklmnopqrstuvwxyz234567" for ch in body):
        raise InvalidCidError("CIDv1 body is not valid base32")
    # RFC4648 base32 alphabet is uppercase; pad to a multiple of 8.
    padded = body.upper() + ("=" * ((8 - (len(body) % 8)) % 8))
    try:
        return base64.b32decode(padded, casefold=True)
    except (binascii.Error, ValueError) as error:
        raise InvalidCidError("CIDv1 body failed base32 decode") from error


def looks_like_cid(value: str) -> bool:
    """Return whether *value* is shaped like a multiformats CID text form."""

    if not isinstance(value, str) or not value:
        return False
    if _CID_LOOKING_RE.fullmatch(value):
        return True
    if _CID_IMPOSTOR_RE.fullmatch(value):
        return True
    # CIDv0 base58btc (legacy) also counts as CID-looking.
    if value.startswith("Qm") and len(value) >= 46 and value.isalnum():
        return True
    return False


def is_structurally_valid_cid_v1(value: str) -> bool:
    """Return whether *value* is a structurally valid CIDv1 base32 string.

    Validation is dependency-free: decode multibase base32, require CIDv1, and
    require a complete multicodec + multihash prefix.  The shared IR identity
    profile (raw + sha2-256) is accepted; other CIDv1 multicodec/multihash
    combinations that decode cleanly are also accepted so long as the stream is
    well-formed.
    """

    if not isinstance(value, str) or not _CID_LOOKING_RE.fullmatch(value):
        return False
    try:
        raw = _base32_decode_cid_body(value[1:])
        version, offset = _varint_read(raw, 0)
        if version != CID_VERSION:
            return False
        _codec, offset = _varint_read(raw, offset)
        mh_code, offset = _varint_read(raw, offset)
        mh_len, offset = _varint_read(raw, offset)
        if mh_len <= 0 or offset + mh_len != len(raw):
            return False
        # Reject empty multihash payloads even if length claims zero (handled).
        if mh_code == MULTIHASH_CODE and mh_len != DIGEST_SIZE:
            # sha2-256 must be exactly 32 bytes when claimed.
            return False
        return True
    except (InvalidCidError, ValueError, TypeError):
        return False


def require_valid_cid(value: object, field_name: str = "cid") -> str:
    """Require a structurally valid CIDv1; reject CID-looking impostors."""

    if not isinstance(value, str) or not value or value != value.strip():
        raise InvalidCidError(
            f"{field_name} must be a non-empty trimmed CIDv1 string"
        )
    if looks_like_cid(value) and not is_structurally_valid_cid_v1(value):
        raise InvalidCidError(
            f"{field_name} looks like a CID but is not a valid CIDv1: {value!r}"
        )
    if not is_structurally_valid_cid_v1(value):
        raise InvalidCidError(
            f"{field_name} must be a structurally valid CIDv1 base32 string"
        )
    return value


def require_digest(value: object, field_name: str) -> str:
    """Require a non-empty ``sha256:<hex>`` digest (bare hex is normalized)."""

    if value is None:
        raise EmptyDigestError(f"{field_name} digest is required")
    if not isinstance(value, str):
        raise CanonicalCacheKeyError(
            f"{field_name} must be a sha256 digest string"
        )
    text = value.strip()
    if not text or text != value:
        # Empty, whitespace-only, or surrounding whitespace fails closed.
        raise EmptyDigestError(
            f"{field_name} must be a non-empty trimmed sha256 digest"
        )
    if text == "sha256:" or text.lower() == "sha256:":
        raise EmptyDigestError(f"{field_name} digest must not be empty")
    if _BARE_DIGEST_RE.fullmatch(text):
        text = f"sha256:{text}"
    if not _DIGEST_RE.fullmatch(text):
        # CID-looking values in digest slots are rejected as impostors.
        if looks_like_cid(text):
            raise InvalidCidError(
                f"{field_name} expected a digest but received a CID-looking "
                f"value: {text!r}"
            )
        raise CanonicalCacheKeyError(
            f"{field_name} must be a sha256:<64-hex> digest; got {value!r}"
        )
    return text


def _reject_default_unknown(value: str, field_name: str) -> str:
    lowered = value.strip().lower()
    if lowered in _DEFAULT_UNKNOWN_PLACEHOLDERS:
        raise CanonicalCacheKeyError(
            f"{field_name} rejects default-string unknown placeholder {value!r}"
        )
    return value


def require_stable_id(value: object, field_name: str) -> str:
    """Require a non-empty stable identifier that is not a placeholder."""

    if not isinstance(value, str) or not value or value != value.strip():
        raise CanonicalCacheKeyError(
            f"{field_name} must be a non-empty trimmed identifier"
        )
    _reject_default_unknown(value, field_name)
    if "\x00" in value:
        raise CanonicalCacheKeyError(f"{field_name} must not contain NUL")
    # If the stable id is CID-shaped, it must be a real CID.
    if looks_like_cid(value):
        return require_valid_cid(value, field_name)
    return value


def _enum_value(enum_type: type[Any], value: object, field_name: str) -> Any:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(getattr(value, "value", value)))
    except (TypeError, ValueError) as error:
        allowed = ", ".join(repr(member.value) for member in enum_type)
        raise CanonicalCacheKeyError(
            f"{field_name} must be one of {allowed}; got {value!r}"
        ) from error


def is_candidate_evidence_kind(kind: LogicEvidenceKind | str) -> bool:
    """Return whether *kind* is a candidate / non-proof evidence format."""

    resolved = _enum_value(LogicEvidenceKind, kind, "evidence_kind")
    return resolved in _CANDIDATE_EVIDENCE_KINDS


def is_kernel_grade_authority(
    authority: LogicEvidenceAuthority | str,
) -> bool:
    """Return whether *authority* is a kernel-grade trust ceiling."""

    resolved = _enum_value(
        LogicEvidenceAuthority, authority, "authority_ceiling"
    )
    return resolved in _KERNEL_GRADE_AUTHORITY


def reject_candidate_as_kernel(
    evidence_kind: LogicEvidenceKind | str,
    authority_ceiling: LogicEvidenceAuthority | str,
) -> None:
    """Fail closed when candidate evidence claims kernel-grade authority."""

    kind = _enum_value(LogicEvidenceKind, evidence_kind, "evidence_kind")
    authority = _enum_value(
        LogicEvidenceAuthority, authority_ceiling, "authority_ceiling"
    )
    if kind in _CANDIDATE_EVIDENCE_KINDS and authority in _KERNEL_GRADE_AUTHORITY:
        raise CandidateAsKernelError(
            "candidate-as-kernel entry rejected: evidence_kind="
            f"{kind.value!r} cannot claim authority_ceiling={authority.value!r}"
        )


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def content_digest(value: Any) -> str:
    """Return a ``sha256:<hex>`` digest of canonical JSON."""

    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def digest_of(value: Any) -> str:
    """Digest a raw value, preserving already-canonical digests and CIDs."""

    if isinstance(value, str):
        text = value.strip()
        if _DIGEST_RE.fullmatch(text):
            return text
        if _BARE_DIGEST_RE.fullmatch(text):
            return f"sha256:{text}"
        if looks_like_cid(text):
            return require_valid_cid(text, "digest_of")
    if value is None:
        raise EmptyDigestError("cannot digest None as a cache identity")
    return content_digest(value)


# ---------------------------------------------------------------------------
# Key type
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CanonicalProofCacheKey:
    """Content-addressed identity of one semantic proof-cache slot.

    All required identity fields are bound at construction.  Changing any field
    yields a distinct ``key_id``.  Candidate evidence cannot claim kernel-grade
    authority on the same key.
    """

    source: str
    expression: str
    formalization: str
    slice: str
    obligation: str
    assumptions: str
    bounds: str
    translation: str
    provider: str
    environment: str
    policy: str
    schema: str
    checker: str
    network_policy: str
    evidence_kind: LogicEvidenceKind
    authority_ceiling: LogicEvidenceAuthority
    schema_version: str = CANONICAL_PROOF_CACHE_KEY_SCHEMA_VERSION
    # Optional content CID for the source snapshot; when set must be valid.
    source_cid: str = ""

    def __post_init__(self) -> None:
        for field_name in _DIGEST_FIELDS:
            object.__setattr__(
                self,
                field_name,
                require_digest(getattr(self, field_name), field_name),
            )
        for field_name in _STABLE_ID_FIELDS:
            object.__setattr__(
                self,
                field_name,
                require_stable_id(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "evidence_kind",
            _enum_value(
                LogicEvidenceKind, self.evidence_kind, "evidence_kind"
            ),
        )
        object.__setattr__(
            self,
            "authority_ceiling",
            _enum_value(
                LogicEvidenceAuthority,
                self.authority_ceiling,
                "authority_ceiling",
            ),
        )
        if not isinstance(self.schema_version, str) or not self.schema_version:
            raise CanonicalCacheKeyError("schema_version is required")
        if self.schema_version != CANONICAL_PROOF_CACHE_KEY_SCHEMA_VERSION:
            raise CanonicalCacheKeyError(
                f"unsupported cache key schema: {self.schema_version!r}"
            )
        if self.source_cid:
            object.__setattr__(
                self,
                "source_cid",
                require_valid_cid(self.source_cid, "source_cid"),
            )
        reject_candidate_as_kernel(self.evidence_kind, self.authority_ceiling)

    # -- construction -------------------------------------------------------

    @classmethod
    def build(
        cls,
        *,
        source: Any,
        expression: Any,
        formalization: Any,
        slice: Any,
        obligation: Any,
        assumptions: Any = (),
        bounds: Any = None,
        translation: Any = None,
        provider: str,
        environment: Any,
        policy: Any,
        schema: Any,
        checker: str,
        network_policy: Any,
        evidence_kind: LogicEvidenceKind | str,
        authority_ceiling: LogicEvidenceAuthority | str,
        source_cid: str = "",
    ) -> CanonicalProofCacheKey:
        """Build a key from raw values, digesting content-addressed dimensions."""

        return cls(
            source=digest_of(source),
            expression=digest_of(expression),
            formalization=digest_of(formalization),
            slice=digest_of(slice),
            obligation=digest_of(obligation),
            assumptions=digest_of(assumptions),
            bounds=digest_of({} if bounds is None else bounds),
            translation=digest_of({} if translation is None else translation),
            provider=provider,
            environment=digest_of(environment),
            policy=digest_of(policy),
            schema=digest_of(schema),
            checker=checker,
            network_policy=digest_of(network_policy),
            evidence_kind=evidence_kind,  # type: ignore[arg-type]
            authority_ceiling=authority_ceiling,  # type: ignore[arg-type]
            source_cid=source_cid,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CanonicalProofCacheKey:
        """Admit a mapping as a :class:`CanonicalProofCacheKey` (fail-closed)."""

        if not isinstance(value, Mapping):
            raise CanonicalCacheKeyError("cache key must be a mapping")
        payload = dict(value)
        missing = [
            name for name in REQUIRED_IDENTITY_FIELDS if name not in payload
        ]
        if missing:
            raise CanonicalCacheKeyError(
                "missing required identity field(s): " + ", ".join(missing)
            )
        allowed = set(REQUIRED_IDENTITY_FIELDS) | {
            "schema_version",
            "source_cid",
            "interface",
            "key_id",
        }
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise CanonicalCacheKeyError(
                "unknown cache key field(s): " + ", ".join(unknown)
            )
        return cls(
            source=payload["source"],
            expression=payload["expression"],
            formalization=payload["formalization"],
            slice=payload["slice"],
            obligation=payload["obligation"],
            assumptions=payload["assumptions"],
            bounds=payload["bounds"],
            translation=payload["translation"],
            provider=payload["provider"],
            environment=payload["environment"],
            policy=payload["policy"],
            schema=payload["schema"],
            checker=payload["checker"],
            network_policy=payload["network_policy"],
            evidence_kind=payload["evidence_kind"],
            authority_ceiling=payload["authority_ceiling"],
            schema_version=payload.get(
                "schema_version", CANONICAL_PROOF_CACHE_KEY_SCHEMA_VERSION
            ),
            source_cid=payload.get("source_cid", "") or "",
        )

    # -- projection ---------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "assumptions": self.assumptions,
            "authority_ceiling": self.authority_ceiling.value,
            "bounds": self.bounds,
            "checker": self.checker,
            "environment": self.environment,
            "evidence_kind": self.evidence_kind.value,
            "expression": self.expression,
            "formalization": self.formalization,
            "interface": CANONICAL_PROOF_CACHE_KEY_INTERFACE,
            "network_policy": self.network_policy,
            "obligation": self.obligation,
            "policy": self.policy,
            "provider": self.provider,
            "schema": self.schema,
            "schema_version": self.schema_version,
            "slice": self.slice,
            "source": self.source,
            "translation": self.translation,
        }
        if self.source_cid:
            payload["source_cid"] = self.source_cid
        return payload

    @property
    def key_id(self) -> str:
        """Stable content id of this key (``canonical-proof-cache-key:sha256:…``)."""

        return f"canonical-proof-cache-key:{content_digest(self.to_dict())}"

    @property
    def digest(self) -> str:
        return content_digest(self.to_dict())

    def binds_required_identity_fields(self) -> bool:
        """Return True when every required identity field is present and non-empty."""

        payload = self.to_dict()
        return all(
            field_name in payload and payload[field_name] not in (None, "")
            for field_name in REQUIRED_IDENTITY_FIELDS
        )


def key_carries_required_identity_fields(
    key: CanonicalProofCacheKey | Mapping[str, Any],
) -> bool:
    """Inventory check for the sixteen LPC-G080 identity fields."""

    if isinstance(key, CanonicalProofCacheKey):
        return key.binds_required_identity_fields()
    if not isinstance(key, Mapping):
        return False
    return all(
        field_name in key and key[field_name] not in (None, "")
        for field_name in REQUIRED_IDENTITY_FIELDS
    )


def admit_canonical_cache_key(
    value: CanonicalProofCacheKey | Mapping[str, Any],
) -> CanonicalProofCacheKey:
    """Admit a typed key or mapping; revalidates every identity field."""

    if isinstance(value, CanonicalProofCacheKey):
        # Rebuild to re-run validators (frozen instances may be reconstructed).
        return CanonicalProofCacheKey.from_dict(value.to_dict())
    return CanonicalProofCacheKey.from_dict(value)


def admit_cache_hit(
    stored: CanonicalProofCacheKey | Mapping[str, Any],
    request: CanonicalProofCacheKey | Mapping[str, Any],
) -> CanonicalProofCacheKey:
    """Admit a cache hit only when identity matches, including environment.

    Cross-environment hits fail closed even when every other field matches.
    Candidate-as-kernel pairings are rejected during key admission.
    """

    stored_key = admit_canonical_cache_key(stored)
    request_key = admit_canonical_cache_key(request)
    if stored_key.environment != request_key.environment:
        raise CrossEnvironmentHitError(
            "cross-environment cache hit rejected: stored environment "
            f"{stored_key.environment!r} != request environment "
            f"{request_key.environment!r}"
        )
    if stored_key.key_id != request_key.key_id:
        raise CanonicalCacheKeyError(
            "cache hit identity mismatch: stored key_id "
            f"{stored_key.key_id!r} != request key_id {request_key.key_id!r}"
        )
    return stored_key


def environments_compatible(
    left: CanonicalProofCacheKey | Mapping[str, Any] | str,
    right: CanonicalProofCacheKey | Mapping[str, Any] | str,
) -> bool:
    """Return whether two keys (or raw environment digests) share environment."""

    def _env(value: CanonicalProofCacheKey | Mapping[str, Any] | str) -> str:
        if isinstance(value, CanonicalProofCacheKey):
            return value.environment
        if isinstance(value, Mapping):
            return require_digest(value.get("environment", ""), "environment")
        return require_digest(value, "environment")

    return _env(left) == _env(right)


def make_identity_cid(payload: Any) -> str:
    """Return a profile CIDv1 for *payload* (helper for tests and adapters)."""

    return cid_v1(_canonical_bytes(payload) if not isinstance(payload, (bytes, bytearray)) else payload)


def make_identity_digest(payload: Any) -> str:
    """Return a ``sha256:`` digest for *payload* bytes or canonical JSON."""

    if isinstance(payload, (bytes, bytearray, memoryview)):
        return sha256_digest(payload)
    return content_digest(payload)


__all__ = [
    "CANONICAL_PROOF_CACHE_KEY_GENERATION",
    "CANONICAL_PROOF_CACHE_KEY_INTERFACE",
    "CANONICAL_PROOF_CACHE_KEY_MODULE_VERSION",
    "CANONICAL_PROOF_CACHE_KEY_SCHEMA",
    "CANONICAL_PROOF_CACHE_KEY_SCHEMA_VERSION",
    "REQUIRED_IDENTITY_FIELDS",
    "CanonicalCacheKeyError",
    "CanonicalProofCacheKey",
    "CandidateAsKernelError",
    "CrossEnvironmentHitError",
    "EmptyDigestError",
    "InvalidCidError",
    "admit_cache_hit",
    "admit_canonical_cache_key",
    "content_digest",
    "digest_of",
    "environments_compatible",
    "is_candidate_evidence_kind",
    "is_kernel_grade_authority",
    "is_structurally_valid_cid_v1",
    "key_carries_required_identity_fields",
    "looks_like_cid",
    "make_identity_cid",
    "make_identity_digest",
    "reject_candidate_as_kernel",
    "require_digest",
    "require_stable_id",
    "require_valid_cid",
]
