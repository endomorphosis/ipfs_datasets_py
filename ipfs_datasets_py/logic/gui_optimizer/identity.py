"""Canonical GUI content identity and provenance (VGO-010).

Implements a closed, dependency-free CIDv1 / SHA-256 identity profile for the
VerifiedGuiOptimizer package.  Identities are domain-separated, rehashable from
retained canonical bytes, and independent of line-number provenance.

Wire interfaces:

* ``GuiCanonicalIdentity@1`` — domain-separated identity result
* ``GuiArtifactDigest@1`` — SHA-256 digest of normalized artifact material
* ``UiComponentVersionCompiler@1`` — stable identity + material → version

TypeScript mirrors this module as ``TypeScriptGuiCanonicalIdentity@1``.

The profile reuses the same CIDv1 / raw / sha2-256 / base32 wire form as the
reviewed ``ir_core.identity`` primitives but binds the GUI optimizer
canonicalization label and never imports semantic-index, proof-cache, or
model-routing code.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from .models import (
    UiComponentIdentity,
    UiComponentVersion,
)
from .schema import (
    CANONICAL_JSON_PROFILE,
    UI_COMPONENT_IDENTITY_INTERFACE,
    UI_COMPONENT_IDENTITY_SCHEMA,
    UI_COMPONENT_VERSION_INTERFACE,
    UI_COMPONENT_VERSION_SCHEMA,
    UiComponentKind,
    parse_enum,
    require_extractor_version,
    require_identifier,
)

# ---------------------------------------------------------------------------
# Profile constants (fixed wire form)
# ---------------------------------------------------------------------------

IDENTITY_PROFILE_NAME: Final = "gui-optimizer-canonical-identity/v1"
GUI_CANONICAL_IDENTITY_INTERFACE: Final = "GuiCanonicalIdentity@1"
GUI_CANONICAL_IDENTITY_SCHEMA: Final = "gui-canonical-identity/v1"
GUI_ARTIFACT_DIGEST_INTERFACE: Final = "GuiArtifactDigest@1"
GUI_ARTIFACT_DIGEST_SCHEMA: Final = "gui-artifact-digest/v1"
UI_COMPONENT_VERSION_COMPILER_INTERFACE: Final = "UiComponentVersionCompiler@1"
UI_COMPONENT_VERSION_COMPILER_SCHEMA: Final = "ui-component-version-compiler/v1"

# Domain labels for domain separation (never part of unrelated domains).
DOMAIN_STABLE_IDENTITY: Final = "gui.stable-identity"
DOMAIN_COMPONENT_VERSION: Final = "gui.component-version"
DOMAIN_ARTIFACT: Final = "gui.artifact"
DOMAIN_APPLICATION: Final = "gui.application-identity"
DOMAIN_SCREEN: Final = "gui.screen-identity"

CID_VERSION: Final = 1
MULTICODEC_NAME: Final = "raw"
MULTICODEC_CODE: Final = 0x55
MULTIHASH_NAME: Final = "sha2-256"
MULTIHASH_CODE: Final = 0x12
DIGEST_SIZE: Final = 32
MULTIBASE_NAME: Final = "base32"

# Provenance-only keys excluded from version material normalization.
_PROVENANCE_KEYS: Final = frozenset(
    {
        "line",
        "column",
        "start_line",
        "end_line",
        "start_column",
        "end_column",
        "absolute_path",
        "checkout_path",
        "source_path",
        "file_path",
        "path",
        "comments",
        "comment",
        "span",
        "source_span",
        "offset",
        "byte_offset",
        "char_offset",
    }
)

_WS_RE: Final = re.compile(r"[ \t]+")
_ABS_PATH_RE: Final = re.compile(r"^(/|[A-Za-z]:[\\/])")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class GuiIdentityError(ValueError):
    """Raised when GUI identity encoding or verification fails."""


# ---------------------------------------------------------------------------
# Profile descriptor
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IdentityProfile:
    """Machine-readable declaration of the fixed GUI identity profile."""

    name: str = IDENTITY_PROFILE_NAME
    canonicalization: str = CANONICAL_JSON_PROFILE
    digest: str = "sha256"
    digest_size: int = DIGEST_SIZE
    cid_version: int = CID_VERSION
    multicodec: str = MULTICODEC_NAME
    multicodec_code: int = MULTICODEC_CODE
    multihash: str = MULTIHASH_NAME
    multihash_code: int = MULTIHASH_CODE
    multibase: str = MULTIBASE_NAME

    def to_dict(self) -> dict[str, str | int]:
        return {
            "canonicalization": self.canonicalization,
            "cid_version": self.cid_version,
            "digest": self.digest,
            "digest_size": self.digest_size,
            "multibase": self.multibase,
            "multicodec": self.multicodec,
            "multicodec_code": self.multicodec_code,
            "multihash": self.multihash,
            "multihash_code": self.multihash_code,
            "name": self.name,
        }


IDENTITY_PROFILE: Final = IdentityProfile()


# ---------------------------------------------------------------------------
# Result records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GuiCanonicalIdentity:
    """Domain-separated CIDv1 / SHA-256 identity (GuiCanonicalIdentity@1)."""

    profile: str
    domain: str
    schema_version: str
    canonical_bytes: bytes
    digest: str
    cid: str
    interface: str = GUI_CANONICAL_IDENTITY_INTERFACE
    wire_schema_version: str = GUI_CANONICAL_IDENTITY_SCHEMA

    @property
    def hexdigest(self) -> str:
        return self.digest.removeprefix("sha256:")

    @property
    def identifier(self) -> str:
        return self.cid

    def to_dict(self) -> dict[str, str]:
        """JSON-ready metadata excluding the byte preimage."""

        return {
            "cid": self.cid,
            "digest": self.digest,
            "domain": self.domain,
            "interface": self.interface,
            "profile": self.profile,
            "schema_version": self.schema_version,
            "wire_schema_version": self.wire_schema_version,
        }

    def rehash(self) -> GuiCanonicalIdentity:
        """Recompute digest and CID from retained canonical bytes."""

        raw = hashlib.sha256(self.canonical_bytes).digest()
        recomputed = GuiCanonicalIdentity(
            profile=self.profile,
            domain=self.domain,
            schema_version=self.schema_version,
            canonical_bytes=self.canonical_bytes,
            digest=f"sha256:{raw.hex()}",
            cid=cid_v1_from_digest(raw),
            interface=self.interface,
            wire_schema_version=self.wire_schema_version,
        )
        if recomputed.digest != self.digest or recomputed.cid != self.cid:
            raise GuiIdentityError(
                "identity does not rehash from retained canonical bytes"
            )
        return recomputed


@dataclass(frozen=True, slots=True)
class GuiArtifactDigest:
    """SHA-256 digest of normalized artifact material (GuiArtifactDigest@1)."""

    digest: str
    cid: str
    domain: str
    canonical_bytes: bytes
    interface: str = GUI_ARTIFACT_DIGEST_INTERFACE
    schema_version: str = GUI_ARTIFACT_DIGEST_SCHEMA

    def to_dict(self) -> dict[str, str]:
        return {
            "cid": self.cid,
            "digest": self.digest,
            "domain": self.domain,
            "interface": self.interface,
            "schema_version": self.schema_version,
        }

    def rehash(self) -> GuiArtifactDigest:
        raw = hashlib.sha256(self.canonical_bytes).digest()
        recomputed = GuiArtifactDigest(
            digest=f"sha256:{raw.hex()}",
            cid=cid_v1_from_digest(raw),
            domain=self.domain,
            canonical_bytes=self.canonical_bytes,
            interface=self.interface,
            schema_version=self.schema_version,
        )
        if recomputed.digest != self.digest or recomputed.cid != self.cid:
            raise GuiIdentityError(
                "artifact digest does not rehash from retained canonical bytes"
            )
        return recomputed


# ---------------------------------------------------------------------------
# Low-level CID / digest primitives (dependency-free)
# ---------------------------------------------------------------------------


def _varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("unsigned varints cannot encode negative values")
    output = bytearray()
    while value >= 0x80:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def sha256_digest(data: bytes | bytearray | memoryview) -> str:
    """Return ``sha256:<hex>`` for raw *data*."""

    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("sha256_digest expects bytes-like input")
    return f"sha256:{hashlib.sha256(bytes(data)).hexdigest()}"


def cid_v1_from_digest(digest: bytes | bytearray | memoryview) -> str:
    """Encode a 32-byte SHA-256 digest as CIDv1 / raw / base32."""

    raw_digest = bytes(digest)
    if len(raw_digest) != DIGEST_SIZE:
        raise ValueError(
            f"{MULTIHASH_NAME} digest must be exactly {DIGEST_SIZE} bytes"
        )
    multihash = _varint(MULTIHASH_CODE) + _varint(DIGEST_SIZE) + raw_digest
    cid_bytes = _varint(CID_VERSION) + _varint(MULTICODEC_CODE) + multihash
    encoded = base64.b32encode(cid_bytes).decode("ascii").rstrip("=").lower()
    return "b" + encoded


def cid_v1(data: bytes | bytearray | memoryview) -> str:
    """Return CIDv1 for raw *data* under the fixed profile."""

    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("cid_v1 expects bytes-like input")
    return cid_v1_from_digest(hashlib.sha256(bytes(data)).digest())


def parse_cid_v1(cid: str) -> dict[str, Any]:
    """Decode and validate a fixed-profile CIDv1 string."""

    if not isinstance(cid, str) or not cid.startswith("b"):
        raise GuiIdentityError("CID must be a lowercase base32 multibase string")
    if cid != cid.lower():
        raise GuiIdentityError("CID must be lowercase")
    padded = cid[1:].upper()
    pad_len = (8 - (len(padded) % 8)) % 8
    try:
        raw = base64.b32decode(padded + ("=" * pad_len))
    except Exception as exc:
        raise GuiIdentityError("CID is not decodable base32") from exc
    # Fixed layout: version(1) + multicodec(1) + mh_code(1) + mh_len(1) + digest(32)
    if len(raw) != 36:
        raise GuiIdentityError("CID byte length is not the fixed raw/sha2-256 form")
    if raw[0] != CID_VERSION or raw[1] != MULTICODEC_CODE:
        raise GuiIdentityError("CID must be CIDv1 with raw multicodec")
    if raw[2] != MULTIHASH_CODE or raw[3] != DIGEST_SIZE:
        raise GuiIdentityError("CID must use sha2-256 with a 32-byte digest")
    digest = raw[4:]
    recomputed = cid_v1_from_digest(digest)
    if recomputed != cid:
        raise GuiIdentityError("CID is not in canonical base32 form")
    return {
        "version": CID_VERSION,
        "multicodec": MULTICODEC_NAME,
        "multicodec_code": MULTICODEC_CODE,
        "multihash": MULTIHASH_NAME,
        "multihash_code": MULTIHASH_CODE,
        "digest": digest.hex(),
        "digest_label": f"sha256:{digest.hex()}",
        "cid": cid,
    }


# ---------------------------------------------------------------------------
# Canonical JSON (GUI optimizer profile)
# ---------------------------------------------------------------------------


def _normalize_text(value: str, *, label: str) -> str:
    if not isinstance(value, str):
        raise GuiIdentityError(f"{label} must be a string")
    normalized = unicodedata.normalize("NFC", value)
    try:
        normalized.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise GuiIdentityError(
            f"{label} contains an unpaired Unicode surrogate"
        ) from exc
    return normalized


def _canonical_number(value: int | float) -> str:
    if isinstance(value, bool):
        raise TypeError("booleans are not numbers")
    if isinstance(value, int):
        return str(value)
    if not math.isfinite(value):
        raise GuiIdentityError("canonical JSON numbers must be finite")
    # Match models.canonical_model_bytes: Python json for finite floats.
    text = json.dumps(value, allow_nan=False, separators=(",", ":"))
    return text


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize *value* under the GUI optimizer canonical JSON profile.

    Rules:

    * NFC-normalized text and map keys;
    * map keys sorted by Unicode code point;
    * finite numbers only;
    * compact UTF-8 JSON (``ensure_ascii=False``);
    * reject bytes, sets, tuples, non-string keys, and host objects.
    """

    return _encode_canonical(value, path="$")


def _encode_canonical(value: Any, *, path: str) -> bytes:
    if value is None:
        return b"null"
    if value is True:
        return b"true"
    if value is False:
        return b"false"
    if type(value) is str:
        normalized = _normalize_text(value, label=path)
        return json.dumps(
            normalized, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    if type(value) is int:
        return str(value).encode("ascii")
    if type(value) is float:
        return _canonical_number(value).encode("ascii")
    if type(value) is dict:
        ready: dict[str, Any] = {}
        originals: dict[str, str] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise GuiIdentityError(f"{path} map keys must be strings")
            nfc = _normalize_text(key, label=f"{path} key")
            if nfc in ready:
                raise GuiIdentityError(
                    f"map keys collide after NFC at {path}: "
                    f"{originals[nfc]!r} and {key!r}"
                )
            ready[nfc] = item
            originals[nfc] = key
        parts: list[bytes] = []
        for key in sorted(ready):
            encoded_key = json.dumps(
                key, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
            encoded_value = _encode_canonical(ready[key], path=f"{path}.{key}")
            parts.append(encoded_key + b":" + encoded_value)
        return b"{" + b",".join(parts) + b"}"
    if type(value) is list:
        parts = [
            _encode_canonical(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
        return b"[" + b",".join(parts) + b"]"
    if isinstance(value, Mapping):
        return _encode_canonical(dict(value), path=path)
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray, memoryview)
    ):
        return _encode_canonical(list(value), path=path)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _encode_canonical(value.to_dict(), path=path)
    raise GuiIdentityError(
        f"{path} is not JSON-serializable for identity: {type(value).__name__}"
    )


def canonical_json(value: Any) -> str:
    """Return the UTF-8 text form of :func:`canonical_json_bytes`."""

    return canonical_json_bytes(value).decode("utf-8")


# ---------------------------------------------------------------------------
# Domain-separated identity
# ---------------------------------------------------------------------------


def _normalized_discriminator(value: str, *, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    normalized = unicodedata.normalize("NFC", value)
    if not normalized or normalized.strip() != normalized:
        raise GuiIdentityError(
            f"{label} must be non-empty and have no surrounding whitespace"
        )
    try:
        normalized.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise GuiIdentityError(
            f"{label} contains an unpaired Unicode surrogate"
        ) from exc
    return normalized


def identity_preimage(
    payload: Any,
    *,
    domain: str,
    schema_version: str,
) -> bytes:
    """Return domain- and schema-separated canonical preimage bytes."""

    normalized_domain = _normalized_discriminator(domain, label="domain")
    normalized_version = _normalized_discriminator(
        schema_version, label="schema_version"
    )
    payload_bytes = canonical_json_bytes(payload)
    # Assemble envelope fields in map-key order with embedded payload bytes.
    fields = (
        (b'"canonicalization":', canonical_json_bytes(CANONICAL_JSON_PROFILE)),
        (b'"domain":', canonical_json_bytes(normalized_domain)),
        (b'"identity_profile":', canonical_json_bytes(IDENTITY_PROFILE_NAME)),
        (b'"payload":', payload_bytes),
        (b'"schema_version":', canonical_json_bytes(normalized_version)),
    )
    return b"{" + b",".join(key + value for key, value in fields) + b"}"


def canonical_identity(
    payload: Any,
    *,
    domain: str,
    schema_version: str,
) -> GuiCanonicalIdentity:
    """Compute a domain-separated GUI canonical identity."""

    preimage = identity_preimage(
        payload, domain=domain, schema_version=schema_version
    )
    raw = hashlib.sha256(preimage).digest()
    return GuiCanonicalIdentity(
        profile=IDENTITY_PROFILE_NAME,
        domain=_normalized_discriminator(domain, label="domain"),
        schema_version=_normalized_discriminator(
            schema_version, label="schema_version"
        ),
        canonical_bytes=preimage,
        digest=f"sha256:{raw.hex()}",
        cid=cid_v1_from_digest(raw),
    )


# Intuitive aliases.
compute_identity = canonical_identity
identity_for = canonical_identity


def verify_identity(
    identity: GuiCanonicalIdentity,
    payload: Any,
    *,
    domain: str | None = None,
    schema_version: str | None = None,
) -> GuiCanonicalIdentity:
    """Recompute identity from *payload* and require an exact match."""

    expected = identity.rehash()
    recomputed = canonical_identity(
        payload,
        domain=domain if domain is not None else identity.domain,
        schema_version=(
            schema_version
            if schema_version is not None
            else identity.schema_version
        ),
    )
    if (
        recomputed.digest != expected.digest
        or recomputed.cid != expected.cid
        or recomputed.canonical_bytes != expected.canonical_bytes
    ):
        raise GuiIdentityError(
            "claimed identity does not match recomputed payload identity"
        )
    return recomputed


# ---------------------------------------------------------------------------
# Artifact digests
# ---------------------------------------------------------------------------


def artifact_digest(
    material: Any,
    *,
    domain: str = DOMAIN_ARTIFACT,
) -> GuiArtifactDigest:
    """Digest normalized artifact material (GuiArtifactDigest@1)."""

    normalized = normalize_material(material)
    preimage = canonical_json_bytes(normalized)
    raw = hashlib.sha256(preimage).digest()
    return GuiArtifactDigest(
        digest=f"sha256:{raw.hex()}",
        cid=cid_v1_from_digest(raw),
        domain=_normalized_discriminator(domain, label="domain"),
        canonical_bytes=preimage,
    )


def facet_digest(material: Any) -> str:
    """Return ``sha256:<hex>`` for one normalized material facet."""

    return artifact_digest(material).digest


# ---------------------------------------------------------------------------
# Material normalization (excludes provenance / nonsemantic noise)
# ---------------------------------------------------------------------------


def normalize_material(value: Any) -> Any:
    """Normalize component material for version digests.

    Drops provenance-only keys (line numbers, absolute paths, comments, spans),
    NFC-normalizes text, collapses nonsemantic interior whitespace in strings,
    and sorts mapping keys.  Does not invent structure.
    """

    return _normalize_value(value)


def _normalize_value(value: Any) -> Any:
    if value is None or type(value) is bool or type(value) is int:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise GuiIdentityError("material rejects non-finite numbers")
        return value
    if type(value) is str:
        text = unicodedata.normalize("NFC", value)
        # Collapse nonsemantic runs of spaces/tabs; preserve newlines as single
        # separators so multi-line structure remains distinguishable.
        text = _WS_RE.sub(" ", text)
        text = re.sub(r"\n+", "\n", text).strip()
        if _ABS_PATH_RE.match(text):
            # Absolute checkout paths are never version authority.
            return ""
        return text
    if type(value) is list:
        return [_normalize_value(item) for item in value]
    if type(value) is dict or isinstance(value, Mapping):
        ready: dict[str, Any] = {}
        for key, item in dict(value).items():
            if type(key) is not str:
                raise GuiIdentityError("material map keys must be strings")
            nfc = unicodedata.normalize("NFC", key)
            if nfc in _PROVENANCE_KEYS or nfc.lower() in _PROVENANCE_KEYS:
                continue
            ready[nfc] = _normalize_value(item)
        return {key: ready[key] for key in sorted(ready)}
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray, memoryview)
    ):
        return [_normalize_value(item) for item in value]
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _normalize_value(value.to_dict())
    raise GuiIdentityError(
        f"material value type {type(value).__name__} is not identity-safe"
    )


# ---------------------------------------------------------------------------
# Stable logical identity (no line numbers)
# ---------------------------------------------------------------------------


def build_stable_identity(
    *,
    application_id: str,
    qualified_name: str,
    component_kind: Any,
    package_namespace: str,
    screen_id: str = "",
) -> UiComponentIdentity:
    """Build a stable logical component identity without line authority.

    Binds application ID, screen ID, qualified name, component kind, and
    package namespace.  Source spans are never part of this identity.
    """

    # Wire constructors require string enum values, never Python Enum instances.
    if isinstance(component_kind, UiComponentKind):
        kind_value: Any = component_kind.value
    else:
        kind_value = component_kind
    # Validate early so callers get a clear error before construction.
    parse_enum(kind_value, UiComponentKind, "component_kind")
    return UiComponentIdentity(
        application_id=require_identifier(application_id, "application_id"),
        qualified_name=require_identifier(qualified_name, "qualified_name"),
        component_kind=kind_value,
        package_namespace=require_identifier(
            package_namespace, "package_namespace"
        ),
        screen_id=screen_id if screen_id is not None else "",
        interface=UI_COMPONENT_IDENTITY_INTERFACE,
        schema_version=UI_COMPONENT_IDENTITY_SCHEMA,
    )


def stable_identity_record(
    identity: UiComponentIdentity | Mapping[str, Any],
) -> GuiCanonicalIdentity:
    """Domain-separated identity for a stable logical component identity."""

    if isinstance(identity, UiComponentIdentity):
        payload = identity.to_dict()
    elif isinstance(identity, Mapping):
        payload = UiComponentIdentity.from_dict(identity).to_dict()
    else:
        raise TypeError("stable identity requires UiComponentIdentity or mapping")
    return canonical_identity(
        payload,
        domain=DOMAIN_STABLE_IDENTITY,
        schema_version=UI_COMPONENT_IDENTITY_SCHEMA,
    )


# ---------------------------------------------------------------------------
# UiComponentVersionCompiler@1
# ---------------------------------------------------------------------------


_FACET_NAMES: Final = (
    "structure",
    "props",
    "state",
    "handlers",
    "accessibility",
    "styles",
    "actions",
    "localization",
)


def compile_component_version(
    stable_identity: UiComponentIdentity | Mapping[str, Any],
    material: Mapping[str, Any],
    *,
    extractor_version: str,
    optimizer_schema_version: str = UI_COMPONENT_VERSION_SCHEMA,
) -> UiComponentVersion:
    """Compile a ``UiComponentVersion@1`` from stable identity + material.

    Material facets (structure, props, state, handlers, accessibility, styles,
    actions, localization) are normalized before hashing.  Line movement and
    absolute-path noise in material do not affect digests.  Meaningful facet
    changes alter the corresponding digest and therefore the version identity.
    """

    if isinstance(stable_identity, UiComponentIdentity):
        identity = stable_identity
    elif isinstance(stable_identity, Mapping):
        identity = UiComponentIdentity.from_dict(stable_identity)
    else:
        raise TypeError(
            "stable_identity must be UiComponentIdentity or a closed mapping"
        )

    if not isinstance(material, Mapping):
        raise TypeError("material must be a mapping of named facets")

    digests: dict[str, str] = {}
    for name in _FACET_NAMES:
        facet = material.get(name, {} if name != "localization" else {})
        digests[f"{name}_digest"] = facet_digest(facet)

    extractor = require_extractor_version(extractor_version)

    return UiComponentVersion(
        stable_identity=identity,
        structure_digest=digests["structure_digest"],
        props_digest=digests["props_digest"],
        state_digest=digests["state_digest"],
        handlers_digest=digests["handlers_digest"],
        accessibility_digest=digests["accessibility_digest"],
        styles_digest=digests["styles_digest"],
        actions_digest=digests["actions_digest"],
        localization_digest=digests["localization_digest"],
        extractor_version=extractor,
        optimizer_schema_version=optimizer_schema_version,
        interface=UI_COMPONENT_VERSION_INTERFACE,
        schema_version=UI_COMPONENT_VERSION_SCHEMA,
    )


def component_version_identity(
    version: UiComponentVersion | Mapping[str, Any],
) -> GuiCanonicalIdentity:
    """Domain-separated identity for a component version record."""

    if isinstance(version, UiComponentVersion):
        payload = version.to_dict()
    elif isinstance(version, Mapping):
        payload = UiComponentVersion.from_dict(version).to_dict()
    else:
        raise TypeError("version requires UiComponentVersion or mapping")
    return canonical_identity(
        payload,
        domain=DOMAIN_COMPONENT_VERSION,
        schema_version=UI_COMPONENT_VERSION_SCHEMA,
    )


class UiComponentVersionCompiler:
    """Stateful facade for ``UiComponentVersionCompiler@1``."""

    INTERFACE: Final = UI_COMPONENT_VERSION_COMPILER_INTERFACE
    SCHEMA_VERSION: Final = UI_COMPONENT_VERSION_COMPILER_SCHEMA

    def __init__(self, *, extractor_version: str) -> None:
        self.extractor_version = require_extractor_version(extractor_version)

    def compile(
        self,
        stable_identity: UiComponentIdentity | Mapping[str, Any],
        material: Mapping[str, Any],
        *,
        optimizer_schema_version: str = UI_COMPONENT_VERSION_SCHEMA,
    ) -> UiComponentVersion:
        return compile_component_version(
            stable_identity,
            material,
            extractor_version=self.extractor_version,
            optimizer_schema_version=optimizer_schema_version,
        )

    def identity_for(
        self,
        stable_identity: UiComponentIdentity | Mapping[str, Any],
        material: Mapping[str, Any],
        *,
        optimizer_schema_version: str = UI_COMPONENT_VERSION_SCHEMA,
    ) -> GuiCanonicalIdentity:
        version = self.compile(
            stable_identity,
            material,
            optimizer_schema_version=optimizer_schema_version,
        )
        return component_version_identity(version)


def create_component_version_compiler(
    *, extractor_version: str
) -> UiComponentVersionCompiler:
    """Factory for ``UiComponentVersionCompiler@1``."""

    return UiComponentVersionCompiler(extractor_version=extractor_version)


# ---------------------------------------------------------------------------
# Convenience: identity for application / screen wire models
# ---------------------------------------------------------------------------


def application_identity(
    payload: Mapping[str, Any] | Any,
) -> GuiCanonicalIdentity:
    """Domain-separated identity for ``GuiApplicationIdentity@1``."""

    if hasattr(payload, "to_dict"):
        body = payload.to_dict()
    else:
        body = dict(payload)
    return canonical_identity(
        body,
        domain=DOMAIN_APPLICATION,
        schema_version=str(
            body.get("schema_version", "gui-application-identity/v1")
        ),
    )


def screen_identity(
    payload: Mapping[str, Any] | Any,
) -> GuiCanonicalIdentity:
    """Domain-separated identity for ``GuiScreenIdentity@1``."""

    if hasattr(payload, "to_dict"):
        body = payload.to_dict()
    else:
        body = dict(payload)
    return canonical_identity(
        body,
        domain=DOMAIN_SCREEN,
        schema_version=str(body.get("schema_version", "gui-screen-identity/v1")),
    )


def model_identity(
    model: Any,
    *,
    domain: str,
) -> GuiCanonicalIdentity:
    """Identity for any model exposing ``to_dict`` / ``SCHEMA_VERSION``."""

    if hasattr(model, "to_dict"):
        payload = model.to_dict()
        schema = getattr(model, "SCHEMA_VERSION", None) or payload.get(
            "schema_version", "unknown"
        )
    elif isinstance(model, Mapping):
        payload = dict(model)
        schema = payload.get("schema_version", "unknown")
    else:
        raise TypeError("model_identity requires a model or mapping")
    return canonical_identity(
        payload, domain=domain, schema_version=str(schema)
    )


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


__all__ = [
    "CANONICAL_JSON_PROFILE",
    "CID_VERSION",
    "DIGEST_SIZE",
    "DOMAIN_APPLICATION",
    "DOMAIN_ARTIFACT",
    "DOMAIN_COMPONENT_VERSION",
    "DOMAIN_SCREEN",
    "DOMAIN_STABLE_IDENTITY",
    "GUI_ARTIFACT_DIGEST_INTERFACE",
    "GUI_ARTIFACT_DIGEST_SCHEMA",
    "GUI_CANONICAL_IDENTITY_INTERFACE",
    "GUI_CANONICAL_IDENTITY_SCHEMA",
    "IDENTITY_PROFILE",
    "IDENTITY_PROFILE_NAME",
    "MULTIBASE_NAME",
    "MULTICODEC_CODE",
    "MULTICODEC_NAME",
    "MULTIHASH_CODE",
    "MULTIHASH_NAME",
    "UI_COMPONENT_VERSION_COMPILER_INTERFACE",
    "UI_COMPONENT_VERSION_COMPILER_SCHEMA",
    "GuiArtifactDigest",
    "GuiCanonicalIdentity",
    "GuiIdentityError",
    "IdentityProfile",
    "UiComponentVersionCompiler",
    "application_identity",
    "artifact_digest",
    "build_stable_identity",
    "canonical_identity",
    "canonical_json",
    "canonical_json_bytes",
    "cid_v1",
    "cid_v1_from_digest",
    "compile_component_version",
    "component_version_identity",
    "compute_identity",
    "create_component_version_compiler",
    "facet_digest",
    "identity_for",
    "identity_preimage",
    "model_identity",
    "normalize_material",
    "parse_cid_v1",
    "screen_identity",
    "sha256_digest",
    "stable_identity_record",
    "verify_identity",
]
