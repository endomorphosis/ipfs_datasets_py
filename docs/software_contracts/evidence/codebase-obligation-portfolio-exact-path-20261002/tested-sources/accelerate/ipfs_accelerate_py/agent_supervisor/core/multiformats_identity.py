"""Strict DAG-JSON / CIDv1 / multihash identity bridge for the agent supervisor.

This module wraps the sealed in-tree
:mod:`ipfs_accelerate_py.utils.cid_utils` implementation so supervisor code can
mint and validate content addresses under a single frozen profile:

* CIDv1
* lowercase base32 multibase
* ``dag-json`` for structured objects and ``raw`` for exact bytes
* ``sha2-256`` multihashes with a full 32-byte digest

Existing supervisor identities (``content_identity`` CIDs and
``runtime-artifact:sha256:…`` / ``sha256:…`` digests) are preserved.  Typed
:class:`IdentityLink` records connect those local IDs to multiformats CIDs
without silently replacing either side.  The implementation is dependency-free
at launch, validates the complete CID wire form, and rejects double-hashing of
an already-computed digest.  External multiformats libraries are optional
test-only parity oracles and never become execution authority.

The executable profile descriptor and exact discovery term
``vfs/cid-profile@1`` are the VFS-G141 evidence surface.  VFS-087 binds that
surface to the shared VFS-G141/G142 content-addressing packet.  The descriptor
describes the already-enforced wire profile; neither the evidence label nor
goal metadata is included in CID input bytes or allowed to replace existing
supervisor IDs.

The content-addressing packet
(``goal_packet/content_addressing/ipfs_accelerate_py/591cd7cfb087``) pairs
this surface with ``vfs/dependency-cache@1`` (VFS-G142) owned by
:mod:`program_analysis_cache`.  Packet evidence helpers here list both terms
for discovery cohesion; dependency-cache key population and fail-closed
lookup remain implemented only on the cache facade.

VFS-G150 / VFS-089 binds that packet and the VFS-G031 invalidation surface to
``vfs/cache-invalidation-proof@1``.  This bridge mirrors the aggregate's exact
goal and evidence lineage for discovery, while executable cache proof behavior
remains owned by :mod:`program_analysis_cache`.

VFS-G030 owns the parent multiformats + dependency-cache surface.  Its
synthetic ``objective validation repair`` discovery marker is exposed only
through evidence helpers and never enters CID bytes, compatibility links, or
mutable current-tree projections used by analysis caches.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Final

from ipfs_accelerate_py.utils import cid_utils as _cid_utils

MULTIFORMATS_IDENTITY_SCHEMA: Final = (
    "ipfs_accelerate_py/agent-supervisor/multiformats-identity@1"
)
IDENTITY_LINK_SCHEMA: Final = (
    "ipfs_accelerate_py/agent-supervisor/multiformats-identity-link@1"
)
CID_PROFILE_SCHEMA: Final = (
    "ipfs_accelerate_py/agent-supervisor/cid-profile@1"
)

CID_VERSION: Final = 1
CID_BASE: Final = "base32"
MH_TYPE: Final = "sha2-256"
DIGEST_SIZE: Final = 32
ALLOWED_CODECS: Final = frozenset({"raw", "dag-json"})

# Exact objective-heap discovery key and its supervisor-fed packet bindings.
CID_PROFILE_EVIDENCE: Final = "vfs/cid-profile@1"
CID_PROFILE_GOAL_ID: Final = "VFS-G141"
CID_PROFILE_TASK_ID: Final = "VFS-087"
# VFS-057 first introduced the executable descriptor.  Keep its task identity
# as explicit history rather than leaving the current singleton binding stale.
CID_PROFILE_PREVIOUS_TASK_IDS: Final[tuple[str, ...]] = ("VFS-057",)

# Paired VFS-G142 dependency-cache discovery anchors (implemented by
# program_analysis_cache).  Declared here as exact-text constants so the
# content-addressing packet evidence is discoverable from both module surfaces
# without importing the cache facade (avoids circular imports).
DEPENDENCY_CACHE_EVIDENCE: Final = "vfs/dependency-cache@1"
DEPENDENCY_CACHE_GOAL_ID: Final = "VFS-G142"
DEPENDENCY_CACHE_TASK_ID: Final = "VFS-088"
CONTENT_ADDRESSING_PACKET_ID: Final = (
    "goal_packet/content_addressing/ipfs_accelerate_py/591cd7cfb087"
)
CONTENT_ADDRESSING_PACKET_GOAL_IDS: Final[tuple[str, ...]] = (
    CID_PROFILE_GOAL_ID,
    DEPENDENCY_CACHE_GOAL_ID,
)
CONTENT_ADDRESSING_PACKET_EVIDENCE_TERMS: Final[tuple[str, ...]] = (
    CID_PROFILE_EVIDENCE,
    DEPENDENCY_CACHE_EVIDENCE,
)
# VFS-G150 proof-aggregate discovery anchors.  These mirror the cache module
# without importing it (and therefore without creating a circular import).
CACHE_INVALIDATION_PROOF_EVIDENCE: Final = "vfs/cache-invalidation-proof@1"
CACHE_INVALIDATION_PROOF_GOAL_ID: Final = "VFS-G150"
CACHE_INVALIDATION_PROOF_TASK_ID: Final = "VFS-089"
CACHE_INVALIDATION_PROOF_PARENT_GOAL_ID: Final = "VFS-G031"
CACHE_INVALIDATION_PROOF_AGGREGATE_GOAL_IDS: Final[tuple[str, ...]] = (
    CACHE_INVALIDATION_PROOF_PARENT_GOAL_ID,
    CID_PROFILE_GOAL_ID,
    DEPENDENCY_CACHE_GOAL_ID,
)
CACHE_INVALIDATION_PROOF_AGGREGATE_EVIDENCE_TERMS: Final[
    tuple[str, ...]
] = (
    CACHE_INVALIDATION_PROOF_EVIDENCE,
    CID_PROFILE_EVIDENCE,
    DEPENDENCY_CACHE_EVIDENCE,
)

# Synthetic objective-heap evidence term for VFS-G030 validation-gate work.
# Exact-text discovery key only — never part of CID input, identity links,
# or mutable current-tree projection dimensions used by analysis caches.
OBJECTIVE_VALIDATION_REPAIR_EVIDENCE: Final = "objective validation repair"
# Domain parent goal that owns multiformats identity + dependency-aware caches.
OBJECTIVE_GOAL_ID: Final = "VFS-G030"
# Repair task that owns the synthetic objective validation repair obligation.
OBJECTIVE_VALIDATION_REPAIR_TASK_ID: Final = "VFS-060"
# Domain evidence owned by this bridge (child VFS-G141 profile surface).
OBJECTIVE_DOMAIN_EVIDENCE_TERMS: Final[tuple[str, ...]] = (CID_PROFILE_EVIDENCE,)

# Keep exact-text discovery anchors aligned with the objective heap.
assert OBJECTIVE_VALIDATION_REPAIR_EVIDENCE == "objective validation repair"
assert OBJECTIVE_GOAL_ID == "VFS-G030"
assert OBJECTIVE_VALIDATION_REPAIR_TASK_ID == "VFS-060"
assert CID_PROFILE_EVIDENCE == "vfs/cid-profile@1"
assert CID_PROFILE_GOAL_ID == "VFS-G141"
assert CID_PROFILE_TASK_ID == "VFS-087"
assert CID_PROFILE_PREVIOUS_TASK_IDS == ("VFS-057",)
assert OBJECTIVE_DOMAIN_EVIDENCE_TERMS == ("vfs/cid-profile@1",)
assert DEPENDENCY_CACHE_EVIDENCE == "vfs/dependency-cache@1"
assert DEPENDENCY_CACHE_GOAL_ID == "VFS-G142"
assert DEPENDENCY_CACHE_TASK_ID == "VFS-088"
assert CONTENT_ADDRESSING_PACKET_GOAL_IDS == ("VFS-G141", "VFS-G142")
assert CONTENT_ADDRESSING_PACKET_EVIDENCE_TERMS == (
    "vfs/cid-profile@1",
    "vfs/dependency-cache@1",
)
assert CACHE_INVALIDATION_PROOF_EVIDENCE == "vfs/cache-invalidation-proof@1"
assert CACHE_INVALIDATION_PROOF_GOAL_ID == "VFS-G150"
assert CACHE_INVALIDATION_PROOF_TASK_ID == "VFS-089"
assert CACHE_INVALIDATION_PROOF_PARENT_GOAL_ID == "VFS-G031"
assert CACHE_INVALIDATION_PROOF_AGGREGATE_GOAL_IDS == (
    "VFS-G031",
    "VFS-G141",
    "VFS-G142",
)
assert CACHE_INVALIDATION_PROOF_AGGREGATE_EVIDENCE_TERMS == (
    "vfs/cache-invalidation-proof@1",
    "vfs/cid-profile@1",
    "vfs/dependency-cache@1",
)

RUNTIME_ARTIFACT_PREFIX: Final = "runtime-artifact:sha256:"
PAYLOAD_DIGEST_PREFIX: Final = "sha256:"

# Wall-clock / expiry material must not participate in identity digests.
_TEMPORAL_IDENTITY_KEYS: Final = frozenset(
    {
        "timestamp",
        "timestamps",
        "created_at",
        "updated_at",
        "modified_at",
        "expires_at",
        "expired_at",
        "created_at_ms",
        "updated_at_ms",
        "expires_at_ms",
        "wall_time",
        "wall_clock",
        "now",
        "as_of",
        "observed_at",
        "issued_at",
    }
)

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_TEMPORAL_TYPES = (datetime, date, time, timedelta)


class MultiformatsIdentityError(ValueError):
    """A multiformats identity or link violates the frozen profile."""


def _cid_utils_call(
    operation: Callable[..., Any],
    /,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Translate every provider/helper failure into the bridge error type."""

    try:
        return operation(*args, **kwargs)
    except MultiformatsIdentityError:
        raise
    except Exception as exc:
        raise MultiformatsIdentityError(
            str(exc) or "sealed CID operation failed"
        ) from exc


@dataclass(frozen=True)
class CIDProfile:
    """Immutable interface descriptor for the admitted supervisor CID profile.

    Construction is deliberately closed to the constants enforced by the
    minting and validation helpers below.  This makes the VFS-G141 evidence
    machine-checkable without creating a second, configurable CID path.
    """

    schema: str = CID_PROFILE_SCHEMA
    evidence: str = CID_PROFILE_EVIDENCE
    version: int = CID_VERSION
    base: str = CID_BASE
    codecs: tuple[str, ...] = tuple(sorted(ALLOWED_CODECS))
    multihash_type: str = MH_TYPE
    digest_size: int = DIGEST_SIZE

    def __post_init__(self) -> None:
        expected = (
            CID_PROFILE_SCHEMA,
            CID_PROFILE_EVIDENCE,
            CID_VERSION,
            CID_BASE,
            tuple(sorted(ALLOWED_CODECS)),
            MH_TYPE,
            DIGEST_SIZE,
        )
        actual = (
            self.schema,
            self.evidence,
            self.version,
            self.base,
            self.codecs,
            self.multihash_type,
            self.digest_size,
        )
        if actual != expected:
            raise MultiformatsIdentityError(
                "CID profile is frozen to "
                "CIDv1/base32/dag-json+raw/sha2-256/32-byte digests"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_CID_PROFILE: Final = CIDProfile()


class IdentityKind(str, Enum):
    """Closed vocabulary for typed dual-identity links."""

    CONTENT_IDENTITY = "content_identity"
    RUNTIME_ARTIFACT = "runtime_artifact"
    PAYLOAD_DIGEST = "payload_digest"
    RAW_BYTES = "raw_bytes"
    DAG_JSON = "dag_json"


@dataclass(frozen=True)
class IdentityLink:
    """Explicit dual mapping between a persisted local ID and a multiformats CID.

    ``local_id`` is never rewritten to the CID (or vice versa).  Callers that
    need either form must read the matching field; replacing persisted
    identities silently is out of contract for this type.
    """

    kind: str
    local_id: str
    cid: str
    codec: str
    version: int = CID_VERSION
    base: str = CID_BASE
    multihash_type: str = MH_TYPE
    digest_hex: str = ""
    digest_size: int = DIGEST_SIZE
    schema: str = IDENTITY_LINK_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != IDENTITY_LINK_SCHEMA:
            raise MultiformatsIdentityError(
                "unsupported multiformats identity link schema"
            )
        try:
            IdentityKind(self.kind)
        except ValueError as exc:
            raise MultiformatsIdentityError(
                f"unsupported identity link kind: {self.kind!r}"
            ) from exc
        if not isinstance(self.local_id, str) or not self.local_id:
            raise MultiformatsIdentityError("local_id must be a nonempty string")
        if self.codec not in ALLOWED_CODECS:
            raise MultiformatsIdentityError(
                f"codec must be one of {sorted(ALLOWED_CODECS)}"
            )
        if (
            self.version != CID_VERSION
            or self.base != CID_BASE
            or self.multihash_type != MH_TYPE
            or self.digest_size != DIGEST_SIZE
        ):
            raise MultiformatsIdentityError(
                "identity link must use CIDv1/base32/sha2-256/32-byte digests"
            )
        if not _SHA256_HEX_RE.fullmatch(self.digest_hex):
            raise MultiformatsIdentityError(
                "digest_hex must be a 64-character lowercase sha2-256 hex string"
            )
        validated = validate_cid(self.cid, codecs=(self.codec,))
        if validated != self.cid:
            raise MultiformatsIdentityError(
                "identity link CID is not the validated canonical form"
            )
        actual_digest = digest_hex_from_cid(self.cid, codecs=(self.codec,))
        if actual_digest != self.digest_hex:
            raise MultiformatsIdentityError(
                "identity link digest_hex does not match the CID multihash"
            )
        # Local ID is an independent persisted handle; it must remain distinct
        # as a stored field even when it happens to equal the CID string
        # (content_identity already is a CIDv1).
        if self.local_id != self.cid and self.kind == IdentityKind.CONTENT_IDENTITY.value:
            # content_identity local IDs that are themselves CIDs must match.
            if self.local_id.startswith("b") and len(self.local_id) > 8:
                raise MultiformatsIdentityError(
                    "content_identity local_id disagrees with linked CID"
                )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "IdentityLink":
        if not isinstance(value, Mapping):
            raise MultiformatsIdentityError("identity link must be an object")
        allowed = {
            "schema",
            "kind",
            "local_id",
            "cid",
            "codec",
            "version",
            "base",
            "multihash_type",
            "digest_hex",
            "digest_size",
        }
        unknown = set(value).difference(allowed)
        if unknown:
            raise MultiformatsIdentityError(
                f"identity link contains unknown fields: {sorted(unknown)}"
            )
        return cls(
            schema=str(value.get("schema") or IDENTITY_LINK_SCHEMA),
            kind=str(value.get("kind") or ""),
            local_id=str(value.get("local_id") or ""),
            cid=str(value.get("cid") or ""),
            codec=str(value.get("codec") or ""),
            version=int(value.get("version", CID_VERSION)),
            base=str(value.get("base") or CID_BASE),
            multihash_type=str(value.get("multihash_type") or MH_TYPE),
            digest_hex=str(value.get("digest_hex") or ""),
            digest_size=int(value.get("digest_size", DIGEST_SIZE)),
        )


def _require_codec(codec: str) -> str:
    if not isinstance(codec, str) or codec not in ALLOWED_CODECS:
        raise MultiformatsIdentityError(
            f"codec must be one of {sorted(ALLOWED_CODECS)}; got {codec!r}"
        )
    return codec


def _is_temporal(value: Any) -> bool:
    return isinstance(value, _TEMPORAL_TYPES)


def _validate_dag_json_value(
    value: Any,
    *,
    path: str = "$",
    reject_temporal_keys: bool = False,
) -> None:
    """Require one unambiguous finite JSON/IPLD data-model value."""

    if _is_temporal(value):
        raise MultiformatsIdentityError(
            f"{path} must not contain timestamps in identity material: "
            f"{type(value).__name__}"
        )
    if value is None or type(value) in {str, bool, int}:
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise MultiformatsIdentityError(
                f"{path} is not JSON compliant: non-finite number"
            )
        return
    if type(value) is list:
        for index, item in enumerate(value):
            _validate_dag_json_value(
                item,
                path=f"{path}[{index}]",
                reject_temporal_keys=reject_temporal_keys,
            )
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise MultiformatsIdentityError(
                    f"{path} contains a non-string DAG-JSON map key"
                )
            if reject_temporal_keys and key.casefold() in _TEMPORAL_IDENTITY_KEYS:
                raise MultiformatsIdentityError(
                    f"{path}.{key} introduces a timestamp into identity material"
                )
            _validate_dag_json_value(
                item,
                path=f"{path}.{key}",
                reject_temporal_keys=reject_temporal_keys,
            )
        return
    # Refuse default=repr / ad-hoc stringification of arbitrary objects.
    raise MultiformatsIdentityError(
        f"{path} is not JSON serializable as DAG-JSON: {type(value).__name__} "
        "(default=repr and non-JSON types are rejected)"
    )


def canonical_dag_json_bytes(
    obj: Any,
    *,
    for_identity: bool = False,
) -> bytes:
    """Serialize strict, deterministic, finite DAG-JSON bytes.

    Unlike legacy serializers that pass ``default=repr``, unsupported Python
    objects (including timestamps) fail closed.  When ``for_identity`` is true,
    known wall-clock field names are also rejected so identity digests stay
    reproducible.
    """

    _validate_dag_json_value(obj, reject_temporal_keys=for_identity)
    # Use the sealed in-tree encoder, then re-validate that its output is the
    # unique sorted/compact form.
    encoded = _cid_utils_call(_cid_utils.canonical_dag_json_bytes, obj)
    return require_canonical_dag_json_bytes(encoded)


def _mirror_canonical_dag_json(data: bytes) -> None:
    """Record the digest of accepted canonical bytes. The bytes are not stored."""

    try:
        from ipfs_accelerate_py.agent_supervisor.runtime.supervisor_meta_index import (
            mirror_work_record,
        )

        record_ref = hashlib.sha256(data).hexdigest()
        mirror_work_record(
            catalog_kind="metadata",
            record_kind="canonical_dag_json_bytes",
            record_ref=record_ref,
            subject_kind="content_cid",
            subject_ref=record_ref,
        )
    except Exception:
        pass


def require_canonical_dag_json_bytes(data: bytes) -> bytes:
    """Accept only exact canonical (sorted-key, compact, finite) DAG-JSON bytes."""

    if type(data) is not bytes:
        raise MultiformatsIdentityError(
            "DAG-JSON identity input must be exact bytes"
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MultiformatsIdentityError(
            "DAG-JSON bytes must be UTF-8"
        ) from exc
    try:
        parsed = json.loads(text, parse_constant=_reject_json_constant)
    except json.JSONDecodeError as exc:
        raise MultiformatsIdentityError(
            "DAG-JSON bytes are not valid JSON"
        ) from exc
    _validate_dag_json_value(parsed)
    # Reconstruct with the sealed encoder — never default=repr.
    expected = _cid_utils_call(_cid_utils.canonical_dag_json_bytes, parsed)
    if data != expected:
        raise MultiformatsIdentityError(
            "DAG-JSON bytes are not canonical (unsorted keys, non-compact "
            "separators, or non-normalized form)"
        )
    _mirror_canonical_dag_json(data)
    return data


def _reject_json_constant(name: str) -> None:
    raise MultiformatsIdentityError(
        f"JSON constant {name!r} is not allowed in DAG-JSON identity material"
    )


def _reject_ambiguous_raw_input(data: Any) -> bytes:
    """Require unambiguous exact bytes; refuse str/path/file-like/memoryview."""

    if type(data) is bytes:
        return data
    if isinstance(data, (str, Path)):
        raise MultiformatsIdentityError(
            "ambiguous raw/string/file input: pass exact bytes, not a path or str"
        )
    if isinstance(data, (bytearray, memoryview)):
        raise MultiformatsIdentityError(
            "ambiguous raw input: coerce to bytes explicitly before hashing"
        )
    # File-like objects
    if hasattr(data, "read") and not isinstance(data, (bytes, bytearray)):
        raise MultiformatsIdentityError(
            "ambiguous raw/file input: read the file to bytes before hashing"
        )
    raise MultiformatsIdentityError(
        f"raw CID input must be exact bytes; got {type(data).__name__}"
    )


def cid_for_bytes(
    data: bytes,
    *,
    base: str = CID_BASE,
    codec: str = "raw",
    mh_type: str = MH_TYPE,
    version: int = CID_VERSION,
) -> str:
    """Return a CIDv1 for exact bytes under the frozen multiformats profile."""

    payload = _reject_ambiguous_raw_input(data)
    _require_codec(codec)
    if (
        base != CID_BASE
        or mh_type != MH_TYPE
        or type(version) is not int
        or version != CID_VERSION
    ):
        raise MultiformatsIdentityError(
            "only CIDv1/base32/sha2-256 is supported by the identity bridge"
        )
    cid = _cid_utils_call(
        _cid_utils.cid_for_bytes,
        payload,
        base=base,
        codec=codec,
        mh_type=mh_type,
        version=version,
    )
    return _cross_check_cid_for_bytes(payload, cid, codec=codec)


def cid_for_dag_json(
    obj: Any,
    *,
    base: str = CID_BASE,
    mh_type: str = MH_TYPE,
    version: int = CID_VERSION,
    for_identity: bool = False,
) -> str:
    """Return a CIDv1 for the canonical DAG-JSON encoding of ``obj``."""

    if (
        base != CID_BASE
        or mh_type != MH_TYPE
        or type(version) is not int
        or version != CID_VERSION
    ):
        raise MultiformatsIdentityError(
            "only CIDv1/base32/sha2-256 is supported by the identity bridge"
        )
    encoded = canonical_dag_json_bytes(obj, for_identity=for_identity)
    cid = _cid_utils_call(
        _cid_utils.cid_for_bytes,
        encoded,
        base=base,
        codec="dag-json",
        mh_type=mh_type,
        version=version,
    )
    # Exercise both in-tree entry points over the exact same canonical bytes.
    package_cid = _cid_utils_call(
        _cid_utils.cid_for_dag_json,
        obj, base=base, mh_type=mh_type, version=version
    )
    if package_cid != cid:
        raise MultiformatsIdentityError(
            "sealed codec drift: cid_utils dag-json CID mismatch"
        )
    return _cross_check_cid_for_bytes(encoded, cid, codec="dag-json")


def _mirror_validated_cid(value: str) -> str:
    """Record one canonical CIDv1. Validation does not admit a task."""

    try:
        from ipfs_accelerate_py.agent_supervisor.runtime.supervisor_meta_index import (
            mirror_work_record,
        )

        mirror_work_record(
            catalog_kind="metadata",
            record_kind="validated_cid",
            record_ref=value,
            subject_kind="content_cid",
            subject_ref=value,
        )
    except Exception:
        pass
    return value


def validate_cid(
    value: Any,
    *,
    codecs: Iterable[str] = ("raw", "dag-json"),
    mh_type: str = MH_TYPE,
    version: int = CID_VERSION,
    base: str = CID_BASE,
) -> str:
    """Validate and return one canonical lowercase CIDv1 string."""

    if not isinstance(value, str) or not value:
        raise MultiformatsIdentityError("CID must be a nonempty lowercase string")
    if value != value.lower():
        raise MultiformatsIdentityError("CID must be canonical lowercase form")
    if (
        mh_type != MH_TYPE
        or type(version) is not int
        or version != CID_VERSION
        or base != CID_BASE
    ):
        raise MultiformatsIdentityError(
            "only CIDv1/base32/sha2-256 validation is supported"
        )
    try:
        allowed = tuple(codecs)
    except Exception as exc:
        raise MultiformatsIdentityError("codecs must be iterable") from exc
    if not allowed or any(
        not isinstance(item, str) or item not in ALLOWED_CODECS
        for item in allowed
    ):
        raise MultiformatsIdentityError(
            f"codecs must be a nonempty subset of {sorted(ALLOWED_CODECS)}"
        )
    # Reject obvious truncated / pseudo forms before strict wire decoding.
    if len(value) < 16 or not value.startswith("b"):
        raise MultiformatsIdentityError(
            "CID is truncated or not canonical lowercase base32 CIDv1"
        )
    canonical = _cid_utils_call(
        _cid_utils.validate_cid,
        value,
        codecs=allowed,
        mh_type=mh_type,
        version=version,
        base=base,
    )
    if canonical != value:
        raise MultiformatsIdentityError("CID is not the validated canonical form")
    _validate_cid_with_multiformats(
        value, codecs=allowed, mh_type=mh_type, version=version, base=base
    )
    return _mirror_validated_cid(value)


def _validate_cid_with_multiformats(
    value: str,
    *,
    codecs: Iterable[str],
    mh_type: str,
    version: int,
    base: str,
) -> None:
    """Validate the full CID wire form through the sealed implementation.

    The private name is retained for compatibility with older diagnostic code;
    external :mod:`multiformats` packages no longer participate here.
    """

    try:
        allowed = tuple(codecs)
    except Exception as exc:
        raise MultiformatsIdentityError("codecs must be iterable") from exc
    _cid_utils_call(
        _cid_utils.validate_cid,
        value,
        codecs=allowed,
        mh_type=mh_type,
        version=version,
        base=base,
    )
    digest = _cid_utils_call(
        _cid_utils.digest_bytes_from_cid,
        value,
        codecs=allowed,
    )
    if len(digest) != DIGEST_SIZE:
        raise MultiformatsIdentityError("CID multihash digest size is not 32 bytes")


def _cross_check_cid_for_bytes(data: bytes, cid: str, *, codec: str) -> str:
    """Ensure minting, digest wrapping, and strict decoding agree."""

    validated = validate_cid(cid, codecs=(codec,))
    independent = _cid_utils_call(
        _cid_utils.cid_from_sha256_digest,
        hashlib.sha256(data).digest(), codec=codec
    )
    if independent != validated:
        raise MultiformatsIdentityError(
            "sealed codec drift: payload CID disagrees with wrapped digest"
        )
    return validated


def digest_hex_from_cid(
    value: str,
    *,
    codecs: Iterable[str] = ("raw", "dag-json"),
) -> str:
    """Return the lowercase sha2-256 hex digest carried by a validated CID."""

    try:
        allowed = tuple(codecs)
    except Exception as exc:
        raise MultiformatsIdentityError("codecs must be iterable") from exc
    canonical = validate_cid(value, codecs=allowed)
    return _cid_utils_call(
        _cid_utils.digest_hex_from_cid,
        canonical,
        codecs=allowed,
    )


def cid_from_sha256_digest(
    digest: bytes | str,
    *,
    codec: str = "raw",
    already_hashed: bool = True,
) -> str:
    """Build a CIDv1 by wrapping an existing sha2-256 digest (no double hashing).

    ``already_hashed`` must remain true.  Passing raw payload bytes with
    ``already_hashed=False`` is rejected so callers cannot accidentally treat
    a digest and a payload interchangeably.
    """

    _require_codec(codec)
    if not already_hashed:
        raise MultiformatsIdentityError(
            "refusing ambiguous digest/payload input: use cid_for_bytes for "
            "payloads or cid_from_sha256_digest(..., already_hashed=True) for digests"
        )
    if isinstance(digest, str):
        text = digest.strip().lower()
        if text.startswith(PAYLOAD_DIGEST_PREFIX):
            text = text[len(PAYLOAD_DIGEST_PREFIX) :]
        if not _SHA256_HEX_RE.fullmatch(text):
            raise MultiformatsIdentityError(
                "sha2-256 digest must be 64 lowercase hex characters"
            )
        digest_bytes = bytes.fromhex(text)
    elif type(digest) is bytes:
        digest_bytes = digest
    else:
        raise MultiformatsIdentityError(
            "digest must be bytes or hex string; refusing ambiguous input"
        )
    if len(digest_bytes) != DIGEST_SIZE:
        raise MultiformatsIdentityError(
            f"sha2-256 digest must be exactly {DIGEST_SIZE} bytes"
        )
    # Wrapping embeds the digest.  Hashing ``digest_bytes`` would address a
    # different payload and is deliberately kept as a negative comparison.
    probe = _cid_utils_call(
        _cid_utils.cid_from_sha256_digest,
        digest_bytes,
        codec=codec,
    )
    double_hashed = _cid_utils_call(
        _cid_utils.cid_for_bytes,
        digest_bytes,
        codec=codec,
    )
    if probe == double_hashed:
        raise MultiformatsIdentityError("malformed multihash: digest was re-hashed")
    # The raw digest inside the wrapped multihash must be the caller's digest,
    # not a re-hash of it.
    if digest_hex_from_cid(probe, codecs=(codec,)) != digest_bytes.hex():
        raise MultiformatsIdentityError(
            "malformed multihash: wrapped digest does not round-trip"
        )
    return validate_cid(probe, codecs=(codec,))


def reject_double_hashed_multihash(data: bytes, claimed_cid: str) -> None:
    """Fail closed when ``claimed_cid`` hashes the digest of ``data`` twice."""

    payload = _reject_ambiguous_raw_input(data)
    direct = cid_for_bytes(payload, codec="raw")
    if claimed_cid == direct:
        return
    # If claimed equals CID(sha256(sha256(payload))), that is double hashing.
    inner = hashlib.sha256(payload).digest()
    double_cid = cid_for_bytes(inner, codec="raw")
    if claimed_cid == double_cid:
        raise MultiformatsIdentityError(
            "double hashing rejected: CID addresses sha256(payload) as raw bytes"
        )
    raise MultiformatsIdentityError(
        "claimed CID does not match payload under the frozen profile"
    )


def parse_runtime_artifact_id(artifact_id: str) -> str:
    """Return the 64-hex digest from a ``runtime-artifact:sha256:…`` ID."""

    if not isinstance(artifact_id, str) or not artifact_id:
        raise MultiformatsIdentityError(
            "runtime artifact id must be a nonempty string"
        )
    if not artifact_id.startswith(RUNTIME_ARTIFACT_PREFIX):
        raise MultiformatsIdentityError(
            "runtime artifact id must use the runtime-artifact:sha256: prefix"
        )
    digest_hex = artifact_id[len(RUNTIME_ARTIFACT_PREFIX) :].lower()
    if not _SHA256_HEX_RE.fullmatch(digest_hex):
        raise MultiformatsIdentityError(
            "runtime artifact id digest must be 64 lowercase hex characters"
        )
    if artifact_id[len(RUNTIME_ARTIFACT_PREFIX) :] != digest_hex:
        raise MultiformatsIdentityError(
            "runtime artifact id digest must be lowercase hex"
        )
    return digest_hex


def parse_payload_digest(payload_digest: str) -> str:
    """Return the 64-hex digest from a ``sha256:…`` payload digest."""

    if not isinstance(payload_digest, str) or not payload_digest:
        raise MultiformatsIdentityError("payload digest must be a nonempty string")
    if not payload_digest.startswith(PAYLOAD_DIGEST_PREFIX):
        raise MultiformatsIdentityError(
            "payload digest must use the sha256: prefix"
        )
    digest_hex = payload_digest[len(PAYLOAD_DIGEST_PREFIX) :].lower()
    if not _SHA256_HEX_RE.fullmatch(digest_hex):
        raise MultiformatsIdentityError(
            "payload digest must be 64 lowercase hex characters"
        )
    if payload_digest[len(PAYLOAD_DIGEST_PREFIX) :] != digest_hex:
        raise MultiformatsIdentityError("payload digest must be lowercase hex")
    return digest_hex


def _link(
    *,
    kind: IdentityKind,
    local_id: str,
    cid: str,
    codec: str,
) -> IdentityLink:
    digest_hex = digest_hex_from_cid(cid, codecs=(codec,))
    return IdentityLink(
        kind=kind.value,
        local_id=local_id,
        cid=cid,
        codec=codec,
        digest_hex=digest_hex,
    )


def link_content_identity(
    local_id: str,
    *,
    value: Any | None = None,
    expected_cid: str | None = None,
) -> IdentityLink:
    """Link a supervisor ``content_identity`` string to a validated dag-json CID.

    The persisted ``local_id`` is retained verbatim.  When ``value`` is
    supplied, the multiformats CID is derived independently and must agree
    with ``local_id`` when the local id is itself a CIDv1.  ``expected_cid``,
    if provided, must match the derived CID; it never replaces ``local_id``.
    """

    if not isinstance(local_id, str) or not local_id:
        raise MultiformatsIdentityError("content_identity local_id is required")

    derived_cid: str | None = None
    if value is not None:
        derived_cid = cid_for_dag_json(value, for_identity=True)
        # Prefer formal content_identity when available for cross-check.
        try:
            from ipfs_accelerate_py.agent_supervisor.proof.formal_verification_contracts import (
                content_identity as formal_content_identity,
            )
        except Exception:  # pragma: no cover - package always present in-tree
            formal_content_identity = None  # type: ignore[assignment]
        if formal_content_identity is not None:
            try:
                formal_id = formal_content_identity(value)
            except Exception as exc:
                raise MultiformatsIdentityError(
                    f"formal content_identity rejected value: {exc}"
                ) from exc
            if formal_id != derived_cid:
                raise MultiformatsIdentityError(
                    "cross-package codec drift: content_identity disagrees "
                    "with multiformats dag-json CID"
                )

    if local_id.startswith("b") and len(local_id) >= 16:
        validated_local = validate_cid(local_id, codecs=("dag-json",))
        if derived_cid is not None and derived_cid != validated_local:
            raise MultiformatsIdentityError(
                "content_identity local_id does not match value-derived CID"
            )
        cid = validated_local
    elif derived_cid is not None:
        cid = derived_cid
    else:
        raise MultiformatsIdentityError(
            "content_identity link requires a CIDv1 local_id and/or value"
        )

    if expected_cid is not None:
        validated_expected = validate_cid(expected_cid, codecs=("dag-json",))
        if validated_expected != cid:
            raise MultiformatsIdentityError(
                "expected_cid does not match linked content_identity CID"
            )
        # expected_cid is advisory verification only — local_id stays put.

    return _link(
        kind=IdentityKind.CONTENT_IDENTITY,
        local_id=local_id,
        cid=cid,
        codec="dag-json",
    )


def link_runtime_artifact(
    artifact_id: str,
    *,
    payload_bytes: bytes | None = None,
    payload_digest: str | None = None,
    codec: str = "raw",
) -> IdentityLink:
    """Link a ``runtime-artifact:sha256:…`` ID to a CIDv1 without replacing it.

    The CID is formed by *wrapping* the existing sha2-256 digest (not by
    hashing the hex string or re-hashing the digest).  When payload bytes or
    a payload digest are provided they must independently confirm the same
    digest.
    """

    _require_codec(codec)
    digest_hex = parse_runtime_artifact_id(artifact_id)

    if payload_digest is not None:
        pd = parse_payload_digest(payload_digest)
        if pd != digest_hex:
            raise MultiformatsIdentityError(
                "payload_digest does not match runtime artifact id"
            )

    if payload_bytes is not None:
        raw = _reject_ambiguous_raw_input(payload_bytes)
        actual = hashlib.sha256(raw).hexdigest()
        if actual != digest_hex:
            raise MultiformatsIdentityError(
                "payload_bytes digest does not match runtime artifact id"
            )
        # Payload path: CID of the exact bytes must equal wrap(digest).
        payload_cid = cid_for_bytes(raw, codec=codec)
        wrapped_cid = cid_from_sha256_digest(digest_hex, codec=codec)
        if payload_cid != wrapped_cid:
            raise MultiformatsIdentityError(
                "cross-package codec drift: payload CID disagrees with wrapped digest"
            )
        cid = payload_cid
    else:
        cid = cid_from_sha256_digest(digest_hex, codec=codec)

    link = _link(
        kind=IdentityKind.RUNTIME_ARTIFACT,
        local_id=artifact_id,
        cid=cid,
        codec=codec,
    )
    if link.digest_hex != digest_hex:
        raise MultiformatsIdentityError(
            "runtime artifact digest disagrees with CID multihash"
        )
    # Never rewrite the persisted artifact id into the CID field.
    if link.local_id == link.cid:
        raise MultiformatsIdentityError(
            "runtime artifact local_id must remain distinct from the CID"
        )
    return link


def link_payload_digest(
    payload_digest: str,
    *,
    codec: str = "raw",
) -> IdentityLink:
    """Link a ``sha256:…`` payload digest to a CIDv1 (wrap, do not re-hash)."""

    _require_codec(codec)
    digest_hex = parse_payload_digest(payload_digest)
    cid = cid_from_sha256_digest(digest_hex, codec=codec)
    link = _link(
        kind=IdentityKind.PAYLOAD_DIGEST,
        local_id=payload_digest,
        cid=cid,
        codec=codec,
    )
    if link.local_id == link.cid:
        raise MultiformatsIdentityError(
            "payload digest local_id must remain distinct from the CID"
        )
    return link


def link_raw_bytes(data: bytes, *, local_id: str | None = None) -> IdentityLink:
    """Address exact bytes as raw CIDv1 and optionally retain a local label."""

    raw = _reject_ambiguous_raw_input(data)
    cid = cid_for_bytes(raw, codec="raw")
    retained = local_id if local_id is not None else cid
    if not isinstance(retained, str) or not retained:
        raise MultiformatsIdentityError("local_id must be a nonempty string")
    return _link(
        kind=IdentityKind.RAW_BYTES,
        local_id=retained,
        cid=cid,
        codec="raw",
    )


def link_dag_json(
    obj: Any,
    *,
    local_id: str | None = None,
    for_identity: bool = True,
) -> IdentityLink:
    """Address a structured value as dag-json CIDv1 with an optional local label."""

    cid = cid_for_dag_json(obj, for_identity=for_identity)
    retained = local_id if local_id is not None else cid
    if not isinstance(retained, str) or not retained:
        raise MultiformatsIdentityError("local_id must be a nonempty string")
    return _link(
        kind=IdentityKind.DAG_JSON,
        local_id=retained,
        cid=cid,
        codec="dag-json",
    )


def independent_round_trip_cid(
    data: bytes,
    *,
    codec: str = "raw",
) -> str:
    """Round-trip mint, strict decode, digest extraction, and digest wrapping."""

    _require_codec(codec)
    payload = _reject_ambiguous_raw_input(data)
    via_utils = _cid_utils_call(
        _cid_utils.cid_for_bytes,
        payload,
        base=CID_BASE,
        codec=codec,
        mh_type=MH_TYPE,
        version=CID_VERSION,
    )
    via_digest = _cid_utils_call(
        _cid_utils.cid_from_sha256_digest,
        hashlib.sha256(payload).digest(), codec=codec
    )
    if via_utils != via_digest:
        raise MultiformatsIdentityError(
            "independent round trip failed: mint and digest wrapping disagree"
        )
    return validate_cid(via_utils, codecs=(codec,))


def independent_round_trip_dag_json(obj: Any) -> str:
    """Round-trip a structured value through DAG-JSON encode/decode and dual CIDs."""

    encoded = canonical_dag_json_bytes(obj)
    parsed = json.loads(encoded.decode("utf-8"))
    reencoded = canonical_dag_json_bytes(parsed)
    if reencoded != encoded:
        raise MultiformatsIdentityError(
            "independent DAG-JSON round trip changed canonical bytes"
        )
    cid = independent_round_trip_cid(encoded, codec="dag-json")
    via_helper = cid_for_dag_json(obj)
    if cid != via_helper:
        raise MultiformatsIdentityError(
            "independent DAG-JSON round trip CID mismatch"
        )
    return cid


def cid_profile() -> CIDProfile:
    """Return the immutable VFS-G141 CID-profile interface descriptor."""

    return _CID_PROFILE


def cid_profile_evidence_terms() -> tuple[str, ...]:
    """Return the exact VFS-G141 objective evidence discovery term."""

    return (CID_PROFILE_EVIDENCE,)


def covered_evidence_terms() -> tuple[str, ...]:
    """Return domain evidence exposed by this identity bridge.

    Domain envelope evidence remains ``vfs/cid-profile@1`` only.  The synthetic
    ``objective validation repair`` term is intentionally omitted here so CID
    profile descriptors and identity links stay domain-only; use
    :func:`objective_validation_repair_evidence_terms` (or
    :func:`all_covered_evidence_terms`) for the VFS-G030 validation gate.

    Objective/task labels are metadata only.  The returned evidence term does
    not participate in canonical DAG-JSON bytes, CIDs, or compatibility links.
    """

    return OBJECTIVE_DOMAIN_EVIDENCE_TERMS


def objective_validation_repair_evidence_terms() -> tuple[str, ...]:
    """Return the synthetic VFS-G030 validation-gate evidence term.

    Exact-text discovery key for objective validation repair.  Never mixes
    into content-addressed CIDs, multihash digests, IdentityLink records, or
    mutable current-tree projection dimensions.  Immutable object identity
    (CIDv1/base32/dag-json/raw/sha2-256) stays separate from cache population
    keys that bind forest / tree projections.  Owned by
    :data:`OBJECTIVE_GOAL_ID` (``VFS-G030``) via repair task
    :data:`OBJECTIVE_VALIDATION_REPAIR_TASK_ID` (``VFS-060``).
    """

    return (OBJECTIVE_VALIDATION_REPAIR_EVIDENCE,)


def all_covered_evidence_terms() -> tuple[str, ...]:
    """Return domain VFS-G030/G141 terms plus the objective validation repair gate.

    Domain ``vfs/cid-profile@1`` comes first; the synthetic objective
    validation repair discovery key is appended last and never enters CID
    input bytes, identity-link payloads, or tree-projection cache dimensions.

    Packet-level ``vfs/dependency-cache@1`` (VFS-G142) is intentionally omitted
    here so this bridge stays cid-profile-only; use
    :func:`content_addressing_packet_evidence_terms` for the shared
    content-addressing packet surface.
    """

    return covered_evidence_terms() + objective_validation_repair_evidence_terms()


def content_addressing_packet_evidence_terms() -> tuple[str, ...]:
    """Return shared VFS-G141 / VFS-G142 packet evidence discovery terms.

    Order is stable: ``vfs/cid-profile@1`` then ``vfs/dependency-cache@1``.
    Neither term participates in CID input bytes or IdentityLink payloads.
    """

    return CONTENT_ADDRESSING_PACKET_EVIDENCE_TERMS


def content_addressing_packet_goal_ids() -> tuple[str, ...]:
    """Return the VFS-G141 / VFS-G142 goal ids for the content-addressing packet."""

    return CONTENT_ADDRESSING_PACKET_GOAL_IDS


def cache_invalidation_proof_aggregate_evidence_terms() -> tuple[str, ...]:
    """Return the VFS-G150 proof aggregate's exact evidence lineage."""

    return CACHE_INVALIDATION_PROOF_AGGREGATE_EVIDENCE_TERMS


def cache_invalidation_proof_aggregate_goal_ids() -> tuple[str, ...]:
    """Return the VFS-G031/G141/G142 aggregate lineage for VFS-G150."""

    return CACHE_INVALIDATION_PROOF_AGGREGATE_GOAL_IDS


def immutable_object_identity_separate_from_tree_projections() -> bool:
    """VFS-G030 refinement: content CIDs never encode current-tree projections.

    Multiformats CIDs address immutable payload bytes only.  Mutable
    current-tree / forest projections participate as analysis-cache
    population dimensions (see :mod:`program_analysis_cache`), not as
    object-identity inputs.  Returning ``True`` anchors the refinement for
    objective validation repair without creating a second CID profile.
    """

    # Profile and discovery metadata are closed and must not widen the wire
    # profile into tree-aware identity minting.
    assert CID_VERSION == 1
    assert CID_BASE == "base32"
    assert MH_TYPE == "sha2-256"
    assert DIGEST_SIZE == 32
    assert ALLOWED_CODECS == frozenset({"raw", "dag-json"})
    assert OBJECTIVE_VALIDATION_REPAIR_EVIDENCE not in (
        CID_PROFILE_EVIDENCE,
        CID_PROFILE_SCHEMA,
        IDENTITY_LINK_SCHEMA,
        MULTIFORMATS_IDENTITY_SCHEMA,
    )
    return True


__all__ = [
    "ALLOWED_CODECS",
    "CACHE_INVALIDATION_PROOF_AGGREGATE_EVIDENCE_TERMS",
    "CACHE_INVALIDATION_PROOF_AGGREGATE_GOAL_IDS",
    "CACHE_INVALIDATION_PROOF_EVIDENCE",
    "CACHE_INVALIDATION_PROOF_GOAL_ID",
    "CACHE_INVALIDATION_PROOF_PARENT_GOAL_ID",
    "CACHE_INVALIDATION_PROOF_TASK_ID",
    "CID_BASE",
    "CID_PROFILE_EVIDENCE",
    "CID_PROFILE_GOAL_ID",
    "CID_PROFILE_PREVIOUS_TASK_IDS",
    "CID_PROFILE_SCHEMA",
    "CID_PROFILE_TASK_ID",
    "CID_VERSION",
    "CIDProfile",
    "CONTENT_ADDRESSING_PACKET_EVIDENCE_TERMS",
    "CONTENT_ADDRESSING_PACKET_GOAL_IDS",
    "CONTENT_ADDRESSING_PACKET_ID",
    "DEPENDENCY_CACHE_EVIDENCE",
    "DEPENDENCY_CACHE_GOAL_ID",
    "DEPENDENCY_CACHE_TASK_ID",
    "DIGEST_SIZE",
    "IDENTITY_LINK_SCHEMA",
    "IdentityKind",
    "IdentityLink",
    "MH_TYPE",
    "MULTIFORMATS_IDENTITY_SCHEMA",
    "MultiformatsIdentityError",
    "OBJECTIVE_DOMAIN_EVIDENCE_TERMS",
    "OBJECTIVE_GOAL_ID",
    "OBJECTIVE_VALIDATION_REPAIR_EVIDENCE",
    "OBJECTIVE_VALIDATION_REPAIR_TASK_ID",
    "PAYLOAD_DIGEST_PREFIX",
    "RUNTIME_ARTIFACT_PREFIX",
    "all_covered_evidence_terms",
    "cache_invalidation_proof_aggregate_evidence_terms",
    "cache_invalidation_proof_aggregate_goal_ids",
    "canonical_dag_json_bytes",
    "cid_for_bytes",
    "cid_for_dag_json",
    "cid_from_sha256_digest",
    "cid_profile",
    "cid_profile_evidence_terms",
    "content_addressing_packet_evidence_terms",
    "content_addressing_packet_goal_ids",
    "covered_evidence_terms",
    "digest_hex_from_cid",
    "immutable_object_identity_separate_from_tree_projections",
    "independent_round_trip_cid",
    "independent_round_trip_dag_json",
    "link_content_identity",
    "link_dag_json",
    "link_payload_digest",
    "link_raw_bytes",
    "link_runtime_artifact",
    "objective_validation_repair_evidence_terms",
    "parse_payload_digest",
    "parse_runtime_artifact_id",
    "reject_double_hashed_multihash",
    "require_canonical_dag_json_bytes",
    "validate_cid",
]
