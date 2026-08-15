"""Deterministic repository, source, symbol, test, property, and artifact identities.

Datasets semantic authority (IPS-007).  Every identity is a version-bound,
content-addressed structured record minted through the strict software-contract
CID profile.  Byte-identical states yield identical IDs; admitted content,
path, schema, and canonicalization mutations change the required identity.

Rules:

* reuse ``ipfs_datasets_py.logic.software_contracts.content`` for CID minting;
* reject floats, cycles, duplicate map keys, path ambiguity, pseudo-CIDs, and
  nondeterministic metadata (timestamps, wall-clock, secrets);
* clean trees, dirty overlays, revisions, artifacts, symbols, tests, and
  properties each have an explicit schema;
* imports have no side effects (multiformats is loaded only when a CID is
  minted or validated).
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

# The strict datasets CID provider is imported lazily inside mint/validate
# helpers so this module remains free of optional multiformats / heavy
# package side effects at import time.

IDENTITY_SUBSET: Final[str] = "ips/canonical-identities@1"
IDENTITY_NAMESPACE: Final[str] = (
    "ipfs_datasets_py/logic/zkp/incremental_sealing/identity"
)
SCHEMA_MAJOR: Final[int] = 1
CANONICALIZATION_VERSION: Final[str] = f"ips/canonicalization@{SCHEMA_MAJOR}"
IDENTITY_SCHEMA_VERSION: Final[str] = str(SCHEMA_MAJOR)

REPOSITORY_STATE_SCHEMA: Final[str] = f"{IDENTITY_NAMESPACE}/repository-state@{SCHEMA_MAJOR}"
SOURCE_ARTIFACT_SCHEMA: Final[str] = f"{IDENTITY_NAMESPACE}/source-artifact@{SCHEMA_MAJOR}"
SOURCE_SYMBOL_SCHEMA: Final[str] = f"{IDENTITY_NAMESPACE}/source-symbol@{SCHEMA_MAJOR}"
TEST_SELECTOR_SCHEMA: Final[str] = f"{IDENTITY_NAMESPACE}/test-selector@{SCHEMA_MAJOR}"
PROPERTY_SCHEMA: Final[str] = f"{IDENTITY_NAMESPACE}/property@{SCHEMA_MAJOR}"

TYPED_ABSENCE: Final[str] = "typed_absence"
ABSENCE_TOKEN: Final[str] = "n/a"
MAX_IDENTIFIER_BYTES: Final[int] = 512
MAX_SAFE_INTEGER: Final[int] = (1 << 53) - 1

SECRET_AND_NONDETERMINISTIC_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "private_key",
        "proving_key_bytes",
        "witness",
        "secret",
        "password",
        "created_at",
        "timestamp",
        "wall_clock",
        "mtime",
        "ctime",
        "now",
        "random",
        "uuid",
        "hostname",
        "pid",
    }
)

_PSEUDO_CID_PREFIXES: Final[tuple[str, ...]] = (
    "cid:",
    "Qm",  # CIDv0 base58 multihashes are not the strict profile
    "sha1:",
    "md5:",
)


class IdentityError(ValueError):
    """Canonical identity contract violation."""


# ---------------------------------------------------------------------------
# Path and scalar validation
# ---------------------------------------------------------------------------


def canonicalize_relative_path(path: Any, *, field: str = "path") -> str:
    """Return a strict relative POSIX path without ambiguity.

    Rejects absolute paths, empty segments, ``.`` / ``..``, backslashes,
    drive prefixes, trailing slashes, and control characters.
    """

    if not isinstance(path, str) or not path:
        raise IdentityError(f"{field} must be a non-empty relative path string")
    if path != path.strip() or not path.strip():
        raise IdentityError(f"{field} must not have surrounding whitespace")
    text = path
    if "\\" in text:
        raise IdentityError(f"{field} rejects backslash path separators")
    if "\x00" in text or any(ord(ch) < 32 for ch in text):
        raise IdentityError(f"{field} rejects control characters")
    if text.startswith("/") or text.startswith("~"):
        raise IdentityError(f"{field} must be repository-relative")
    if len(text) >= 2 and text[1] == ":":
        raise IdentityError(f"{field} rejects drive-letter paths")
    if text.endswith("/"):
        raise IdentityError(f"{field} rejects trailing slash ambiguity")
    segments = text.split("/")
    if any(segment == "" for segment in segments):
        raise IdentityError(f"{field} rejects empty path segments")
    if any(segment in {".", ".."} for segment in segments):
        raise IdentityError(f"{field} rejects '.' and '..' path segments")
    if len(text.encode("utf-8")) > MAX_IDENTIFIER_BYTES:
        raise IdentityError(f"{field} exceeds {MAX_IDENTIFIER_BYTES} bytes")
    return text


def _require_identifier(value: Any, field: str, *, allow_absence: bool = False) -> str:
    if allow_absence and value == ABSENCE_TOKEN:
        return ABSENCE_TOKEN
    if not isinstance(value, str) or not value.strip():
        raise IdentityError(f"{field} must be a non-empty string or {ABSENCE_TOKEN}")
    text = value.strip()
    if text != value:
        raise IdentityError(f"{field} must not have surrounding whitespace")
    if len(text.encode("utf-8")) > MAX_IDENTIFIER_BYTES:
        raise IdentityError(f"{field} exceeds {MAX_IDENTIFIER_BYTES} bytes")
    return text


def _require_sorted_unique_strings(value: Any, field: str) -> tuple[str, ...]:
    if value == ABSENCE_TOKEN:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise IdentityError(f"{field} must be a sequence or {ABSENCE_TOKEN}")
    items = tuple(_require_identifier(item, field, allow_absence=False) for item in value)
    if list(items) != sorted(items):
        raise IdentityError(f"{field} must be canonically sorted")
    if len(set(items)) != len(items):
        raise IdentityError(f"{field} must not contain duplicates")
    return items


def _require_nonneg_int(value: Any, field: str) -> int:
    if type(value) is not int or isinstance(value, bool):
        raise IdentityError(f"{field} must be a finite int")
    if value < 0 or value > MAX_SAFE_INTEGER:
        raise IdentityError(f"{field} is out of bounds")
    return value


def _reject_secret_fields(payload: Mapping[str, Any]) -> None:
    leaked = set(payload) & SECRET_AND_NONDETERMINISTIC_FIELDS
    if leaked:
        raise IdentityError(
            f"secret or nondeterministic fields are forbidden: {sorted(leaked)}"
        )


def _reject_cycles(value: Any, *, path: str = "$", seen: set[int] | None = None) -> None:
    """Fail closed on recursive containers that would make identity nondeterministic."""

    if type(value) not in {list, dict}:
        return
    marker = id(value)
    active = seen if seen is not None else set()
    if marker in active:
        raise IdentityError(f"{path} contains a cycle")
    active.add(marker)
    try:
        if type(value) is list:
            for index, item in enumerate(value):
                _reject_cycles(item, path=f"{path}[{index}]", seen=active)
        else:
            for key, item in value.items():
                _reject_cycles(item, path=f"{path}.{key}", seen=active)
    finally:
        active.discard(marker)


def _reject_floats(value: Any, *, path: str = "$") -> None:
    if type(value) is float:
        if not math.isfinite(value):
            raise IdentityError(f"{path} rejects non-finite float")
        raise IdentityError(f"{path} rejects float; use int or reviewed string")
    if type(value) is list:
        for index, item in enumerate(value):
            _reject_floats(item, path=f"{path}[{index}]")
        return
    if type(value) is dict:
        for key, item in value.items():
            _reject_floats(item, path=f"{path}.{key}")


def parse_strict_json(text: str) -> Any:
    """Parse JSON while rejecting duplicate object keys."""

    if not isinstance(text, str):
        raise IdentityError("JSON text must be a string")

    def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise IdentityError(f"duplicate map key {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(text, object_pairs_hook=_object_pairs, parse_constant=_reject_json_constant)
    except IdentityError:
        raise
    except json.JSONDecodeError as exc:
        raise IdentityError(f"invalid JSON: {exc.msg}") from exc


def _reject_json_constant(name: str) -> None:
    raise IdentityError(f"JSON constant {name!r} is forbidden")


# ---------------------------------------------------------------------------
# Canonical CID surface (strict datasets provider)
# ---------------------------------------------------------------------------


def _content_provider() -> Any:
    """Load the strict software-contract CID provider on first use."""

    import importlib

    return importlib.import_module(
        "ipfs_datasets_py.logic.software_contracts.content"
    )


def canonical_cid(value: Any) -> str:
    """Mint a structured (dag-json) CIDv1 for a reviewed identity payload."""

    if isinstance(value, Mapping):
        _reject_secret_fields(value)
    _reject_cycles(value)
    _reject_floats(value)
    provider = _content_provider()
    try:
        provider.validate_structured_value(value)
        return provider.cid_for_structured(value)
    except (
        provider.ContentIdentityError,
        provider.StructuredIdentityError,
        TypeError,
        ValueError,
    ) as exc:
        raise IdentityError(str(exc)) from exc


def canonical_cid_for_bytes(data: bytes) -> str:
    """Mint a source-byte (raw) CIDv1 for exact artifact bytes."""

    if type(data) is not bytes:
        raise IdentityError("source bytes must be exact bytes")
    provider = _content_provider()
    try:
        return provider.cid_for_bytes(data)
    except (provider.ContentIdentityError, TypeError, ValueError) as exc:
        raise IdentityError(str(exc)) from exc


def validate_profile_cid(value: Any, *, domain: str = "structured") -> str:
    """Validate a strict profile CID and reject pseudo-CID forms."""

    if not isinstance(value, str) or not value:
        raise IdentityError("CID must be a nonempty string")
    # Reject pseudo-CIDs before the casing check: CIDv0 (Qm…) is mixed-case.
    for prefix in _PSEUDO_CID_PREFIXES:
        if value.startswith(prefix) or value == prefix.rstrip(":"):
            raise IdentityError(f"pseudo-CID form is rejected: {value!r}")
    if value.startswith("sha256:") or value.startswith("sha2-256:"):
        raise IdentityError(f"pseudo-CID digest form is rejected: {value!r}")
    if value != value.lower():
        raise IdentityError("CID must be lowercase canonical base32")
    codecs = {"raw"} if domain == "source" else {"dag-json"}
    if domain == "any":
        codecs = {"raw", "dag-json"}
    provider = _content_provider()
    try:
        return provider.validate_cid(value, codecs=codecs)
    except (provider.ContentIdentityError, ValueError) as exc:
        raise IdentityError(f"invalid profile CID: {exc}") from exc


# ---------------------------------------------------------------------------
# Identity records
# ---------------------------------------------------------------------------


def _canonical_json(payload: Mapping[str, Any]) -> str:
    _reject_secret_fields(payload)
    _reject_cycles(payload)
    _reject_floats(payload)
    provider = _content_provider()
    try:
        provider.validate_structured_value(payload)
    except (
        provider.ContentIdentityError,
        provider.StructuredIdentityError,
        TypeError,
        ValueError,
    ) as exc:
        raise IdentityError(str(exc)) from exc
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


@dataclass(frozen=True, slots=True)
class RepositoryState:
    """Repository-wide state: clean tree, optional dirty overlay, and revision."""

    repository_id: str
    revision: str
    tree_cid: str
    dirty_overlay_cid: str
    parent_revision_ids: tuple[str, ...]
    canonicalization_version: str = CANONICALIZATION_VERSION
    schema: str = REPOSITORY_STATE_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "repository_id",
            _require_identifier(self.repository_id, "repository_id"),
        )
        object.__setattr__(self, "revision", _require_identifier(self.revision, "revision"))
        object.__setattr__(
            self,
            "tree_cid",
            validate_profile_cid(self.tree_cid, domain="any"),
        )
        if self.dirty_overlay_cid == ABSENCE_TOKEN:
            object.__setattr__(self, "dirty_overlay_cid", ABSENCE_TOKEN)
        else:
            object.__setattr__(
                self,
                "dirty_overlay_cid",
                validate_profile_cid(self.dirty_overlay_cid, domain="any"),
            )
        object.__setattr__(
            self,
            "parent_revision_ids",
            _require_sorted_unique_strings(
                self.parent_revision_ids, "parent_revision_ids"
            ),
        )
        object.__setattr__(
            self,
            "canonicalization_version",
            _require_identifier(
                self.canonicalization_version, "canonicalization_version"
            ),
        )
        object.__setattr__(
            self, "schema", _require_identifier(self.schema, "schema", allow_absence=False)
        )
        if self.schema != REPOSITORY_STATE_SCHEMA:
            raise IdentityError(
                f"repository state schema must be {REPOSITORY_STATE_SCHEMA}"
            )

    @property
    def is_clean(self) -> bool:
        return self.dirty_overlay_cid == ABSENCE_TOKEN

    def to_canonical(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "identity_schema_version": IDENTITY_SCHEMA_VERSION,
            "canonicalization_version": self.canonicalization_version,
            "repository_id": self.repository_id,
            "revision": self.revision,
            "tree_cid": self.tree_cid,
            "dirty_overlay_cid": self.dirty_overlay_cid,
            "parent_revision_ids": (
                list(self.parent_revision_ids)
                if self.parent_revision_ids
                else ABSENCE_TOKEN
            ),
            "typed_absence": TYPED_ABSENCE,
        }

    def to_canonical_json(self) -> str:
        return _canonical_json(self.to_canonical())

    def identity_cid(self) -> str:
        return canonical_cid(self.to_canonical())

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> RepositoryState:
        if not isinstance(payload, Mapping):
            raise IdentityError("RepositoryState payload must be a mapping")
        _reject_secret_fields(payload)
        parents = payload.get("parent_revision_ids", ABSENCE_TOKEN)
        return cls(
            repository_id=str(payload.get("repository_id") or ""),
            revision=str(payload.get("revision") or ""),
            tree_cid=str(payload.get("tree_cid") or ""),
            dirty_overlay_cid=str(payload.get("dirty_overlay_cid") or ""),
            parent_revision_ids=(
                ()
                if parents == ABSENCE_TOKEN
                else tuple(str(item) for item in parents)  # type: ignore[arg-type]
            ),
            canonicalization_version=str(
                payload.get("canonicalization_version") or CANONICALIZATION_VERSION
            ),
            schema=str(payload.get("schema") or REPOSITORY_STATE_SCHEMA),
        )


@dataclass(frozen=True, slots=True)
class SourceArtifactIdentity:
    """One repository-relative source or fixture artifact and its content CID."""

    repository_id: str
    path: str
    content_cid: str
    byte_length: int
    canonicalization_version: str = CANONICALIZATION_VERSION
    schema: str = SOURCE_ARTIFACT_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "repository_id",
            _require_identifier(self.repository_id, "repository_id"),
        )
        object.__setattr__(
            self, "path", canonicalize_relative_path(self.path, field="path")
        )
        object.__setattr__(
            self,
            "content_cid",
            validate_profile_cid(self.content_cid, domain="source"),
        )
        object.__setattr__(
            self, "byte_length", _require_nonneg_int(self.byte_length, "byte_length")
        )
        object.__setattr__(
            self,
            "canonicalization_version",
            _require_identifier(
                self.canonicalization_version, "canonicalization_version"
            ),
        )
        object.__setattr__(
            self, "schema", _require_identifier(self.schema, "schema", allow_absence=False)
        )
        if self.schema != SOURCE_ARTIFACT_SCHEMA:
            raise IdentityError(
                f"source artifact schema must be {SOURCE_ARTIFACT_SCHEMA}"
            )

    def to_canonical(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "identity_schema_version": IDENTITY_SCHEMA_VERSION,
            "canonicalization_version": self.canonicalization_version,
            "repository_id": self.repository_id,
            "path": self.path,
            "content_cid": self.content_cid,
            "byte_length": self.byte_length,
        }

    def to_canonical_json(self) -> str:
        return _canonical_json(self.to_canonical())

    def identity_cid(self) -> str:
        return canonical_cid(self.to_canonical())

    @classmethod
    def from_bytes(
        cls,
        *,
        repository_id: str,
        path: str,
        data: bytes,
        canonicalization_version: str = CANONICALIZATION_VERSION,
    ) -> SourceArtifactIdentity:
        if type(data) is not bytes:
            raise IdentityError("artifact data must be exact bytes")
        return cls(
            repository_id=repository_id,
            path=path,
            content_cid=canonical_cid_for_bytes(data),
            byte_length=len(data),
            canonicalization_version=canonicalization_version,
        )

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> SourceArtifactIdentity:
        if not isinstance(payload, Mapping):
            raise IdentityError("SourceArtifactIdentity payload must be a mapping")
        _reject_secret_fields(payload)
        return cls(
            repository_id=str(payload.get("repository_id") or ""),
            path=str(payload.get("path") or ""),
            content_cid=str(payload.get("content_cid") or ""),
            byte_length=payload.get("byte_length"),  # type: ignore[arg-type]
            canonicalization_version=str(
                payload.get("canonicalization_version") or CANONICALIZATION_VERSION
            ),
            schema=str(payload.get("schema") or SOURCE_ARTIFACT_SCHEMA),
        )


@dataclass(frozen=True, slots=True)
class SourceSymbolIdentity:
    """One stable module/symbol locator bound to its source artifact identity."""

    repository_id: str
    module_path: str
    qualified_name: str
    symbol_kind: str
    source_artifact_id: str
    canonicalization_version: str = CANONICALIZATION_VERSION
    schema: str = SOURCE_SYMBOL_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "repository_id",
            _require_identifier(self.repository_id, "repository_id"),
        )
        object.__setattr__(
            self,
            "module_path",
            canonicalize_relative_path(self.module_path, field="module_path"),
        )
        object.__setattr__(
            self,
            "qualified_name",
            _require_identifier(self.qualified_name, "qualified_name"),
        )
        if " " in self.qualified_name or self.qualified_name.startswith("."):
            raise IdentityError("qualified_name path ambiguity is rejected")
        object.__setattr__(
            self, "symbol_kind", _require_identifier(self.symbol_kind, "symbol_kind")
        )
        object.__setattr__(
            self,
            "source_artifact_id",
            validate_profile_cid(self.source_artifact_id, domain="structured"),
        )
        object.__setattr__(
            self,
            "canonicalization_version",
            _require_identifier(
                self.canonicalization_version, "canonicalization_version"
            ),
        )
        object.__setattr__(
            self, "schema", _require_identifier(self.schema, "schema", allow_absence=False)
        )
        if self.schema != SOURCE_SYMBOL_SCHEMA:
            raise IdentityError(f"source symbol schema must be {SOURCE_SYMBOL_SCHEMA}")

    def to_canonical(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "identity_schema_version": IDENTITY_SCHEMA_VERSION,
            "canonicalization_version": self.canonicalization_version,
            "repository_id": self.repository_id,
            "module_path": self.module_path,
            "qualified_name": self.qualified_name,
            "symbol_kind": self.symbol_kind,
            "source_artifact_id": self.source_artifact_id,
        }

    def to_canonical_json(self) -> str:
        return _canonical_json(self.to_canonical())

    def identity_cid(self) -> str:
        return canonical_cid(self.to_canonical())

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> SourceSymbolIdentity:
        if not isinstance(payload, Mapping):
            raise IdentityError("SourceSymbolIdentity payload must be a mapping")
        _reject_secret_fields(payload)
        return cls(
            repository_id=str(payload.get("repository_id") or ""),
            module_path=str(payload.get("module_path") or ""),
            qualified_name=str(payload.get("qualified_name") or ""),
            symbol_kind=str(payload.get("symbol_kind") or ""),
            source_artifact_id=str(payload.get("source_artifact_id") or ""),
            canonicalization_version=str(
                payload.get("canonicalization_version") or CANONICALIZATION_VERSION
            ),
            schema=str(payload.get("schema") or SOURCE_SYMBOL_SCHEMA),
        )


@dataclass(frozen=True, slots=True)
class TestSelectorIdentity:
    """One collected test node plus canonical parameter case."""

    repository_id: str
    node_id: str
    module_path: str
    function_name: str
    parameter_case: str
    canonicalization_version: str = CANONICALIZATION_VERSION
    schema: str = TEST_SELECTOR_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "repository_id",
            _require_identifier(self.repository_id, "repository_id"),
        )
        object.__setattr__(
            self, "node_id", _require_identifier(self.node_id, "node_id")
        )
        if "\\" in self.node_id or self.node_id != self.node_id.strip():
            raise IdentityError("node_id path ambiguity is rejected")
        object.__setattr__(
            self,
            "module_path",
            canonicalize_relative_path(self.module_path, field="module_path"),
        )
        object.__setattr__(
            self,
            "function_name",
            _require_identifier(self.function_name, "function_name"),
        )
        if self.parameter_case == ABSENCE_TOKEN:
            object.__setattr__(self, "parameter_case", ABSENCE_TOKEN)
        else:
            object.__setattr__(
                self,
                "parameter_case",
                _require_identifier(self.parameter_case, "parameter_case"),
            )
        object.__setattr__(
            self,
            "canonicalization_version",
            _require_identifier(
                self.canonicalization_version, "canonicalization_version"
            ),
        )
        object.__setattr__(
            self, "schema", _require_identifier(self.schema, "schema", allow_absence=False)
        )
        if self.schema != TEST_SELECTOR_SCHEMA:
            raise IdentityError(f"test selector schema must be {TEST_SELECTOR_SCHEMA}")

    def to_canonical(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "identity_schema_version": IDENTITY_SCHEMA_VERSION,
            "canonicalization_version": self.canonicalization_version,
            "repository_id": self.repository_id,
            "node_id": self.node_id,
            "module_path": self.module_path,
            "function_name": self.function_name,
            "parameter_case": self.parameter_case,
            "typed_absence": TYPED_ABSENCE,
        }

    def to_canonical_json(self) -> str:
        return _canonical_json(self.to_canonical())

    def identity_cid(self) -> str:
        return canonical_cid(self.to_canonical())

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> TestSelectorIdentity:
        if not isinstance(payload, Mapping):
            raise IdentityError("TestSelectorIdentity payload must be a mapping")
        _reject_secret_fields(payload)
        return cls(
            repository_id=str(payload.get("repository_id") or ""),
            node_id=str(payload.get("node_id") or ""),
            module_path=str(payload.get("module_path") or ""),
            function_name=str(payload.get("function_name") or ""),
            parameter_case=str(payload.get("parameter_case") or ABSENCE_TOKEN),
            canonicalization_version=str(
                payload.get("canonicalization_version") or CANONICALIZATION_VERSION
            ),
            schema=str(payload.get("schema") or TEST_SELECTOR_SCHEMA),
        )


@dataclass(frozen=True, slots=True)
class PropertyIdentity:
    """One declared formal property / obligation identity."""

    repository_id: str
    property_name: str
    statement_cid: str
    obligation_kind: str
    canonicalization_version: str = CANONICALIZATION_VERSION
    schema: str = PROPERTY_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "repository_id",
            _require_identifier(self.repository_id, "repository_id"),
        )
        object.__setattr__(
            self,
            "property_name",
            _require_identifier(self.property_name, "property_name"),
        )
        object.__setattr__(
            self,
            "statement_cid",
            validate_profile_cid(self.statement_cid, domain="any"),
        )
        object.__setattr__(
            self,
            "obligation_kind",
            _require_identifier(self.obligation_kind, "obligation_kind"),
        )
        object.__setattr__(
            self,
            "canonicalization_version",
            _require_identifier(
                self.canonicalization_version, "canonicalization_version"
            ),
        )
        object.__setattr__(
            self, "schema", _require_identifier(self.schema, "schema", allow_absence=False)
        )
        if self.schema != PROPERTY_SCHEMA:
            raise IdentityError(f"property schema must be {PROPERTY_SCHEMA}")

    def to_canonical(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "identity_schema_version": IDENTITY_SCHEMA_VERSION,
            "canonicalization_version": self.canonicalization_version,
            "repository_id": self.repository_id,
            "property_name": self.property_name,
            "statement_cid": self.statement_cid,
            "obligation_kind": self.obligation_kind,
        }

    def to_canonical_json(self) -> str:
        return _canonical_json(self.to_canonical())

    def identity_cid(self) -> str:
        return canonical_cid(self.to_canonical())

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> PropertyIdentity:
        if not isinstance(payload, Mapping):
            raise IdentityError("PropertyIdentity payload must be a mapping")
        _reject_secret_fields(payload)
        return cls(
            repository_id=str(payload.get("repository_id") or ""),
            property_name=str(payload.get("property_name") or ""),
            statement_cid=str(payload.get("statement_cid") or ""),
            obligation_kind=str(payload.get("obligation_kind") or ""),
            canonicalization_version=str(
                payload.get("canonicalization_version") or CANONICALIZATION_VERSION
            ),
            schema=str(payload.get("schema") or PROPERTY_SCHEMA),
        )


# ---------------------------------------------------------------------------
# Known vectors (clean tree, dirty overlay, revision, artifact, symbol, test, property)
# ---------------------------------------------------------------------------


def known_vectors() -> dict[str, Any]:
    """Return versioned known identity vectors for hermetic regression tests."""

    clean_bytes = b"module main\n"
    dirty_bytes = b"module main\n# dirty\n"
    tree_cid = canonical_cid(
        {
            "entries": [
                {
                    "path": "pkg/main.py",
                    "content_cid": canonical_cid_for_bytes(clean_bytes),
                    "byte_length": len(clean_bytes),
                }
            ]
        }
    )
    dirty_overlay_cid = canonical_cid(
        {
            "entries": [
                {
                    "path": "pkg/main.py",
                    "content_cid": canonical_cid_for_bytes(dirty_bytes),
                    "byte_length": len(dirty_bytes),
                }
            ]
        }
    )
    clean_repo = RepositoryState(
        repository_id="repo/datasets",
        revision="rev-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        tree_cid=tree_cid,
        dirty_overlay_cid=ABSENCE_TOKEN,
        parent_revision_ids=(),
    )
    dirty_repo = RepositoryState(
        repository_id="repo/datasets",
        revision="rev-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        tree_cid=tree_cid,
        dirty_overlay_cid=dirty_overlay_cid,
        parent_revision_ids=(),
    )
    revised_repo = RepositoryState(
        repository_id="repo/datasets",
        revision="rev-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        tree_cid=tree_cid,
        dirty_overlay_cid=ABSENCE_TOKEN,
        parent_revision_ids=("rev-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",),
    )
    artifact = SourceArtifactIdentity.from_bytes(
        repository_id="repo/datasets",
        path="pkg/main.py",
        data=clean_bytes,
    )
    symbol = SourceSymbolIdentity(
        repository_id="repo/datasets",
        module_path="pkg/main.py",
        qualified_name="pkg.main:entry",
        symbol_kind="function",
        source_artifact_id=artifact.identity_cid(),
    )
    test_selector = TestSelectorIdentity(
        repository_id="repo/datasets",
        node_id="tests/test_main.py::test_entry",
        module_path="tests/test_main.py",
        function_name="test_entry",
        parameter_case=ABSENCE_TOKEN,
    )
    statement_cid = canonical_cid(
        {"statement": "forall x. P(x) -> Q(x)", "logic": "fol"}
    )
    property_identity = PropertyIdentity(
        repository_id="repo/datasets",
        property_name="prop/output-soundness",
        statement_cid=statement_cid,
        obligation_kind="formal_obligation",
    )
    return {
        "schema": f"{IDENTITY_NAMESPACE}/known-vectors@{SCHEMA_MAJOR}",
        "identity_subset": IDENTITY_SUBSET,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "vectors": {
            "clean_repository": {
                "payload": clean_repo.to_canonical(),
                "identity_cid": clean_repo.identity_cid(),
            },
            "dirty_overlay_repository": {
                "payload": dirty_repo.to_canonical(),
                "identity_cid": dirty_repo.identity_cid(),
            },
            "revised_repository": {
                "payload": revised_repo.to_canonical(),
                "identity_cid": revised_repo.identity_cid(),
            },
            "source_artifact": {
                "payload": artifact.to_canonical(),
                "identity_cid": artifact.identity_cid(),
            },
            "source_symbol": {
                "payload": symbol.to_canonical(),
                "identity_cid": symbol.identity_cid(),
            },
            "test_selector": {
                "payload": test_selector.to_canonical(),
                "identity_cid": test_selector.identity_cid(),
            },
            "property": {
                "payload": property_identity.to_canonical(),
                "identity_cid": property_identity.identity_cid(),
            },
        },
    }


def build_repository_state(
    *,
    repository_id: str,
    revision: str,
    tree_cid: str,
    dirty_overlay_cid: str = ABSENCE_TOKEN,
    parent_revision_ids: Sequence[str] = (),
    canonicalization_version: str = CANONICALIZATION_VERSION,
) -> RepositoryState:
    """Construct a version-bound repository identity (IPS-017 public freeze)."""

    return RepositoryState(
        repository_id=repository_id,
        revision=revision,
        tree_cid=tree_cid,
        dirty_overlay_cid=dirty_overlay_cid,
        parent_revision_ids=tuple(parent_revision_ids),
        canonicalization_version=canonicalization_version,
    )


__all__ = (
    "ABSENCE_TOKEN",
    "CANONICALIZATION_VERSION",
    "IDENTITY_SCHEMA_VERSION",
    "IDENTITY_SUBSET",
    "PROPERTY_SCHEMA",
    "REPOSITORY_STATE_SCHEMA",
    "SOURCE_ARTIFACT_SCHEMA",
    "SOURCE_SYMBOL_SCHEMA",
    "TEST_SELECTOR_SCHEMA",
    "TYPED_ABSENCE",
    "IdentityError",
    "PropertyIdentity",
    "RepositoryState",
    "SourceArtifactIdentity",
    "SourceSymbolIdentity",
    "TestSelectorIdentity",
    "build_repository_state",
    "canonical_cid",
    "canonical_cid_for_bytes",
    "canonicalize_relative_path",
    "known_vectors",
    "parse_strict_json",
    "validate_profile_cid",
)
