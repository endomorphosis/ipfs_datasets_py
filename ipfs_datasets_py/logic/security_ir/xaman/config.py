"""Explicit, immutable configuration for the Xaman Security IR adapter.

Repository artifact locations and orchestration task identifiers are runtime
configuration.  They intentionally live here rather than in the shared
``SecurityIR`` declaration model.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any, Final

from ...ir_core.canonical import canonical_json_bytes


XAMAN_ADAPTER_CONFIG_VERSION: Final = "xaman-security-adapter-config/v1"
XAMAN_VOCABULARY: Final = "security.xaman"
XAMAN_VOCABULARY_VERSION: Final = "v1"
XAMAN_VOCABULARY_SCHEMA_VERSION: Final = (
    f"{XAMAN_VOCABULARY}/{XAMAN_VOCABULARY_VERSION}"
)
XAMAN_EXTENSION_ID: Final = "extension:security.xaman:v1"
XAMAN_SECURITY_DOMAINS: Final = frozenset(
    {
        "auth_component",
        "e2e_flow",
        "ledger",
        "payload",
        "service",
        "store",
        "vault",
    }
)
XAMAN_ASSUMPTIONS: Final = MappingProxyType(
    {
        "A1": "cryptographic primitives are unbroken",
        "A2": "private keys are generated with sufficient entropy",
        "A3": (
            "signing code signs only approved canonical transaction bytes"
        ),
        "A6": "the declared XRPL finality threshold is sufficient",
        "A9": (
            "external XRPL providers may lie, delay, or censor only within "
            "the modeled bounds"
        ),
    }
)

# These are evidence categories, not claims that the assumptions hold.  They
# are stable Xaman-domain vocabulary and may be replaced by an explicit
# per-deployment mapping in ``XamanAdapterConfig``.
DEFAULT_XAMAN_EVIDENCE_REQUIREMENTS: Final = MappingProxyType(
    {
        "A1": (
            "cryptographic primitive and dependency inventory",
            "cryptographic review bound to the source revision",
        ),
        "A2": (
            "key-generation and entropy-source documentation",
            "key lifecycle and native secret-storage controls",
        ),
        "A3": (
            "deployed signing source digest",
            "approved-intent to canonical-signing-bytes binding",
        ),
        "A6": (
            "XRPL finality and reorganization policy",
            "release-owner acceptance of finality bounds",
        ),
        "A9": (
            "XRPL provider inventory and trust bounds",
            "stale-data, delay, censorship, and fallback policy",
        ),
    }
)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class XamanConfigError(ValueError):
    """Raised when Xaman adapter configuration is unsafe or ambiguous."""


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise XamanConfigError(f"{name} must be a non-empty string")
    if value != value.strip():
        raise XamanConfigError(f"{name} must not have surrounding whitespace")
    return value


def _identifier(value: Any, name: str) -> str:
    result = _text(value, name)
    if not _IDENTIFIER_RE.fullmatch(result):
        raise XamanConfigError(f"{name} must be a stable identifier")
    return result


def _string_mapping(
    value: Mapping[str, str] | None,
    name: str,
    *,
    validate_values_as_identifiers: bool = False,
) -> Mapping[str, str]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise XamanConfigError(f"{name} must be a mapping")
    result: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = _identifier(raw_key, f"{name} key")
        item = (
            _identifier(raw_value, f"{name}[{key!r}]")
            if validate_values_as_identifiers
            else _text(raw_value, f"{name}[{key!r}]")
        )
        result[key] = item
    return MappingProxyType(dict(sorted(result.items())))


def _artifact_paths(value: Mapping[str, str] | None) -> Mapping[str, str]:
    result = _string_mapping(value, "artifact_paths")
    for artifact_id, raw_path in result.items():
        path = PurePosixPath(raw_path)
        if (
            path == PurePosixPath(".")
            or path.is_absolute()
            or ".." in path.parts
            or raw_path != path.as_posix()
        ):
            raise XamanConfigError(
                f"artifact_paths[{artifact_id!r}] must be a normalized "
                "repository-relative POSIX path"
            )
    return result


def _requirement_mapping(
    value: Mapping[str, Sequence[str]] | None,
) -> Mapping[str, tuple[str, ...]]:
    raw = DEFAULT_XAMAN_EVIDENCE_REQUIREMENTS if value is None else value
    if not isinstance(raw, Mapping):
        raise XamanConfigError("evidence_requirements must be a mapping")
    result: dict[str, tuple[str, ...]] = {}
    for raw_assumption_id, raw_items in raw.items():
        assumption_id = _identifier(
            raw_assumption_id, "evidence requirement assumption id"
        )
        if isinstance(raw_items, (str, bytes, bytearray)) or not isinstance(
            raw_items, Sequence
        ):
            raise XamanConfigError(
                f"evidence_requirements[{assumption_id!r}] must be a sequence"
            )
        items = tuple(
            _text(item, f"evidence_requirements[{assumption_id!r}]")
            for item in raw_items
        )
        if not items:
            raise XamanConfigError(
                f"evidence_requirements[{assumption_id!r}] must not be empty"
            )
        if len(items) != len(set(items)):
            raise XamanConfigError(
                f"evidence_requirements[{assumption_id!r}] must be unique"
            )
        result[assumption_id] = items
    return MappingProxyType(dict(sorted(result.items())))


@dataclass(frozen=True, slots=True)
class XamanSourceConfig:
    """A caller-supplied binding to one immutable Xaman source revision."""

    source_id: str
    uri: str
    revision: str
    content_sha256: str = ""
    review_status: str = "unreviewed"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "source_id", _identifier(self.source_id, "source_id")
        )
        object.__setattr__(self, "uri", _text(self.uri, "uri"))
        object.__setattr__(self, "revision", _text(self.revision, "revision"))
        if self.content_sha256 and not _SHA256_RE.fullmatch(self.content_sha256):
            raise XamanConfigError(
                "content_sha256 must be a lowercase SHA-256 hex digest"
            )
        object.__setattr__(
            self,
            "review_status",
            _identifier(self.review_status, "review_status"),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "content_sha256": self.content_sha256,
            "review_status": self.review_status,
            "revision": self.revision,
            "source_id": self.source_id,
            "uri": self.uri,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "XamanSourceConfig":
        if not isinstance(value, Mapping):
            raise XamanConfigError("source config must be a mapping")
        allowed = {
            "source_id",
            "uri",
            "revision",
            "content_sha256",
            "review_status",
        }
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise XamanConfigError(
                "unknown source config field(s): " + ", ".join(unknown)
            )
        return cls(
            source_id=value.get("source_id", ""),
            uri=value.get("uri", ""),
            revision=value.get("revision", ""),
            content_sha256=value.get("content_sha256", ""),
            review_status=value.get("review_status", "unreviewed"),
        )


@dataclass(frozen=True, slots=True)
class XamanAdapterConfig:
    """All explicit source and repository bindings used by the adapter.

    ``task_ids`` and ``artifact_paths`` are carried by the adapter result but
    never copied into the shared declaration.  Consequently moving a checkout
    or renumbering an orchestration task cannot change Security IR identity.
    """

    source: XamanSourceConfig
    config_id: str = "config:xaman-security-adapter"
    task_ids: Mapping[str, str] = field(default_factory=dict)
    artifact_paths: Mapping[str, str] = field(default_factory=dict)
    evidence_requirements: Mapping[str, Sequence[str]] | None = None
    schema_version: str = XAMAN_ADAPTER_CONFIG_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.source, XamanSourceConfig):
            raise XamanConfigError("source must be a XamanSourceConfig")
        object.__setattr__(
            self, "config_id", _identifier(self.config_id, "config_id")
        )
        if self.schema_version != XAMAN_ADAPTER_CONFIG_VERSION:
            raise XamanConfigError(
                f"unsupported Xaman config version: {self.schema_version!r}"
            )
        object.__setattr__(
            self,
            "task_ids",
            _string_mapping(
                self.task_ids,
                "task_ids",
                validate_values_as_identifiers=True,
            ),
        )
        object.__setattr__(
            self, "artifact_paths", _artifact_paths(self.artifact_paths)
        )
        object.__setattr__(
            self,
            "evidence_requirements",
            _requirement_mapping(self.evidence_requirements),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_paths": dict(self.artifact_paths),
            "config_id": self.config_id,
            "evidence_requirements": {
                key: list(values)
                for key, values in self.evidence_requirements.items()
            },
            "schema_version": self.schema_version,
            "source": self.source.to_dict(),
            "task_ids": dict(self.task_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "XamanAdapterConfig":
        if not isinstance(value, Mapping):
            raise XamanConfigError("adapter config must be a mapping")
        allowed = {
            "artifact_paths",
            "config_id",
            "evidence_requirements",
            "schema_version",
            "source",
            "task_ids",
        }
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise XamanConfigError(
                "unknown adapter config field(s): " + ", ".join(unknown)
            )
        return cls(
            source=XamanSourceConfig.from_dict(value.get("source", {})),
            config_id=value.get(
                "config_id", "config:xaman-security-adapter"
            ),
            task_ids=value.get("task_ids", {}),
            artifact_paths=value.get("artifact_paths", {}),
            evidence_requirements=value.get("evidence_requirements"),
            schema_version=value.get(
                "schema_version", XAMAN_ADAPTER_CONFIG_VERSION
            ),
        )

    @property
    def digest(self) -> str:
        """Return the full runtime-configuration digest."""

        import hashlib

        return "sha256:" + hashlib.sha256(
            canonical_json_bytes(self.to_dict())
        ).hexdigest()


# Readable aliases for callers that describe the source as a binding.
XamanSourceBinding = XamanSourceConfig
XamanSecurityAdapterConfig = XamanAdapterConfig


__all__ = [
    "DEFAULT_XAMAN_EVIDENCE_REQUIREMENTS",
    "XAMAN_ADAPTER_CONFIG_VERSION",
    "XAMAN_ASSUMPTIONS",
    "XAMAN_EXTENSION_ID",
    "XAMAN_SECURITY_DOMAINS",
    "XAMAN_VOCABULARY",
    "XAMAN_VOCABULARY_SCHEMA_VERSION",
    "XAMAN_VOCABULARY_VERSION",
    "XamanAdapterConfig",
    "XamanConfigError",
    "XamanSecurityAdapterConfig",
    "XamanSourceBinding",
    "XamanSourceConfig",
]
