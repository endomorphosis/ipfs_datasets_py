"""Domain-neutral, source-grounded inputs to formalization compilers.

The contracts in this module intentionally know nothing about Legal, Security,
or Intent corpora.  A sample carries an immutable normalized declaration and
joins it to exact source bytes through the shared provenance kernel.  Source
bodies, embeddings, compiler output, and verification results do not belong in
this record.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from ipfs_datasets_py.logic.ir_core.claims import (
    Assumption,
    FrozenMap,
)
from ipfs_datasets_py.logic.ir_core.identity import (
    CanonicalIdentity,
    canonical_identity,
)
from ipfs_datasets_py.logic.ir_core.provenance import Provenance


FORMALIZATION_SAMPLE_SCHEMA_VERSION: Final = "formalization-sample/v1"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class FormalizationValidationError(ValueError):
    """Raised when a generic formalization contract is malformed."""


def _text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FormalizationValidationError(f"{field_name} must be a non-empty string")
    if value != value.strip():
        raise FormalizationValidationError(
            f"{field_name} must not have surrounding whitespace"
        )
    return value


def _identifier(value: Any, field_name: str) -> str:
    result = _text(value, field_name)
    if not _ID_RE.fullmatch(result):
        raise FormalizationValidationError(
            f"{field_name} must be a stable identifier"
        )
    return result


def _unique_identifiers(
    values: Sequence[str], field_name: str, *, sort: bool = True
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)):
        raise FormalizationValidationError(
            f"{field_name} must be a sequence of identifiers"
        )
    normalized = tuple(_identifier(value, field_name) for value in values)
    if len(normalized) != len(set(normalized)):
        raise FormalizationValidationError(f"{field_name} values must be unique")
    return tuple(sorted(normalized)) if sort else normalized


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FormalizationValidationError(f"{field_name} must be a mapping")
    return value


def _sequence(value: Any, field_name: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise FormalizationValidationError(f"{field_name} must be a sequence")
    return value


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], record_name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise FormalizationValidationError(
            f"unknown {record_name} field(s): {', '.join(unknown)}"
        )


@dataclass(frozen=True, slots=True)
class FormalizationSample:
    """One immutable, normalized declaration with explicit source grounding.

    ``payload`` is domain-owned normalized JSON.  The generic contract checks
    only immutability and JSON representability; corpus- and ontology-specific
    validation remains the responsibility of an adapter.
    """

    sample_id: str
    domain: str
    declaration_id: str
    declaration_digest: str
    payload: FrozenMap
    provenance: Provenance
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    assumptions: tuple[Assumption, ...] = ()
    tags: tuple[str, ...] = ()
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = FORMALIZATION_SAMPLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "sample_id", _identifier(self.sample_id, "sample_id"))
        object.__setattr__(self, "domain", _identifier(self.domain, "domain"))
        object.__setattr__(
            self,
            "declaration_id",
            _identifier(self.declaration_id, "declaration_id"),
        )
        if not isinstance(self.declaration_digest, str) or not _DIGEST_RE.fullmatch(
            self.declaration_digest
        ):
            raise FormalizationValidationError(
                "declaration_digest must be a lowercase sha256:<hex> digest"
            )
        object.__setattr__(
            self,
            "payload",
            self.payload
            if isinstance(self.payload, FrozenMap)
            else FrozenMap(_mapping(self.payload, "payload")),
        )
        if not isinstance(self.provenance, Provenance):
            raise FormalizationValidationError(
                "provenance must be a shared Provenance instance"
            )
        # Normalize through the kernel's canonical projection.  Besides making
        # construction defensive, this gives typed -> JSON -> typed round trips
        # the same deterministic tuple ordering as direct construction.
        object.__setattr__(
            self,
            "provenance",
            Provenance.from_dict(self.provenance.to_dict()),
        )
        source_ref_ids = _unique_identifiers(
            self.source_ref_ids, "source_ref_ids"
        )
        span_ids = _unique_identifiers(self.span_ids, "span_ids")
        assumptions = tuple(
            item
            if isinstance(item, Assumption)
            else Assumption.from_dict(_mapping(item, "assumption"))
            for item in self.assumptions
        )
        assumption_ids = [item.assumption_id for item in assumptions]
        if len(assumption_ids) != len(set(assumption_ids)):
            raise FormalizationValidationError(
                "assumption IDs must be unique within a sample"
            )
        object.__setattr__(
            self,
            "assumptions",
            tuple(sorted(assumptions, key=lambda item: item.assumption_id)),
        )
        object.__setattr__(self, "source_ref_ids", source_ref_ids)
        object.__setattr__(self, "span_ids", span_ids)
        object.__setattr__(
            self,
            "tags",
            _unique_identifiers(self.tags, "tags"),
        )
        object.__setattr__(
            self,
            "metadata",
            self.metadata
            if isinstance(self.metadata, FrozenMap)
            else FrozenMap(_mapping(self.metadata, "metadata")),
        )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        self.validate()

    def validate(self) -> "FormalizationSample":
        """Validate the sample and all source/provenance cross-references."""

        if self.schema_version != FORMALIZATION_SAMPLE_SCHEMA_VERSION:
            raise FormalizationValidationError(
                f"unsupported formalization sample schema: {self.schema_version!r}"
            )
        try:
            self.provenance.validate()
        except ValueError as exc:
            raise FormalizationValidationError(str(exc)) from exc

        source_ids = {item.ref_id for item in self.provenance.sources}
        spans = {item.span_id: item for item in self.provenance.spans}
        unknown_sources = set(self.source_ref_ids) - source_ids
        unknown_spans = set(self.span_ids) - set(spans)
        if unknown_sources:
            raise FormalizationValidationError(
                "sample references unknown sources: "
                + ", ".join(sorted(unknown_sources))
            )
        if unknown_spans:
            raise FormalizationValidationError(
                "sample references unknown spans: " + ", ".join(sorted(unknown_spans))
            )
        effective_sources = set(self.source_ref_ids)
        effective_sources.update(spans[item].source_ref_id for item in self.span_ids)
        if not effective_sources:
            raise FormalizationValidationError(
                "FormalizationSample must be grounded in at least one source or span"
            )
        if self.source_ref_ids:
            mismatched = {
                span_id
                for span_id in self.span_ids
                if spans[span_id].source_ref_id not in self.source_ref_ids
            }
            if mismatched:
                raise FormalizationValidationError(
                    "sample spans belong to unlisted sources: "
                    + ", ".join(sorted(mismatched))
                )

        subject_ids = {item.subject_id for item in self.provenance.bindings}
        if self.sample_id not in subject_ids and self.declaration_id not in subject_ids:
            raise FormalizationValidationError(
                "provenance must bind the sample_id or declaration_id"
            )
        for assumption in self.assumptions:
            if not assumption.source_refs:
                raise FormalizationValidationError(
                    f"assumption {assumption.assumption_id!r} must be source-grounded"
                )
            unknown = set(assumption.source_refs) - source_ids
            if unknown:
                raise FormalizationValidationError(
                    f"assumption {assumption.assumption_id!r} references unknown "
                    f"sources: {', '.join(sorted(unknown))}"
                )
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumptions": [item.to_dict() for item in self.assumptions],
            "declaration_digest": self.declaration_digest,
            "declaration_id": self.declaration_id,
            "domain": self.domain,
            "metadata": self.metadata.to_dict(),
            "payload": self.payload.to_dict(),
            "provenance": self.provenance.to_dict(),
            "sample_id": self.sample_id,
            "schema_version": self.schema_version,
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
            "tags": list(self.tags),
        }

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.to_dict(),
            domain=f"formalization-sample:{self.domain}",
            schema_version=self.schema_version,
            collection_semantics={
                "/assumptions": "set-like",
                "/source_ref_ids": "set-like",
                "/span_ids": "set-like",
                "/tags": "set-like",
            },
        )

    @property
    def digest(self) -> str:
        return self.identity.digest

    @property
    def sample_digest(self) -> str:
        return self.digest

    @property
    def sample_cid(self) -> str:
        return self.identity.cid

    def canonical_bytes(self) -> bytes:
        return self.identity.canonical_bytes

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FormalizationSample":
        value = _mapping(value, "formalization sample")
        _reject_unknown(
            value,
            frozenset(
                {
                    "assumptions",
                    "declaration_digest",
                    "declaration_id",
                    "domain",
                    "metadata",
                    "payload",
                    "provenance",
                    "sample_id",
                    "schema_version",
                    "source_ref_ids",
                    "span_ids",
                    "tags",
                }
            ),
            "formalization sample",
        )
        return cls(
            sample_id=value.get("sample_id", ""),
            domain=value.get("domain", ""),
            declaration_id=value.get("declaration_id", ""),
            declaration_digest=value.get("declaration_digest", ""),
            payload=FrozenMap(_mapping(value.get("payload", {}), "payload")),
            provenance=Provenance.from_dict(
                _mapping(value.get("provenance", {}), "provenance")
            ),
            source_ref_ids=tuple(
                _sequence(value.get("source_ref_ids", ()), "source_ref_ids")
            ),
            span_ids=tuple(_sequence(value.get("span_ids", ()), "span_ids")),
            assumptions=tuple(
                Assumption.from_dict(_mapping(item, "assumption"))
                for item in _sequence(value.get("assumptions", ()), "assumptions")
            ),
            tags=tuple(_sequence(value.get("tags", ()), "tags")),
            metadata=FrozenMap(_mapping(value.get("metadata", {}), "metadata")),
            schema_version=value.get(
                "schema_version", FORMALIZATION_SAMPLE_SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> "FormalizationSample":
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, UnicodeDecodeError) as exc:
            raise FormalizationValidationError(
                "formalization sample must be valid JSON"
            ) from exc
        return cls.from_dict(_mapping(decoded, "formalization sample"))


__all__ = [
    "FORMALIZATION_SAMPLE_SCHEMA_VERSION",
    "FormalizationSample",
    "FormalizationValidationError",
]
