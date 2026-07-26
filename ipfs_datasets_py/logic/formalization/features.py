"""Versioned, source-free feature vectors for formalization advisors.

Feature artifacts are deliberately less expressive than formalization samples.
They contain a finite numeric vector, never declaration/source text, target
labels, compiler or prover results, retrieval output, or mutable graph state.
Immutable graph and embedding *snapshot identifiers* may be bound as
non-model context so downstream evaluation can prove which corpus was used.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

from ipfs_datasets_py.logic.ir_core.identity import (
    CanonicalIdentity,
    canonical_identity,
)

from .samples import (
    FormalizationSample,
    FormalizationValidationError,
    _identifier,
    _mapping,
    _reject_unknown,
    _sequence,
    _text,
)


FORMALIZATION_FEATURES_SCHEMA_VERSION: Final = "formalization-features/v1"
MAX_FORMALIZATION_FEATURES: Final = 16_384

_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_FEATURE_NAME_RE = re.compile(r"^[a-z][a-z0-9_.:/=-]{0,255}$")
_SNAPSHOT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")

# Exact path components are rejected.  This leaves declaration semantics such
# as ``statement.kind.verification.count`` usable while excluding outputs such
# as ``verification.result`` or ``proof.status``.
_FORBIDDEN_COMPONENTS = frozenset(
    {
        "answer",
        "body",
        "canary",
        "certificate",
        "completion",
        "embedding",
        "evaluation",
        "failed",
        "fold",
        "gold",
        "graph",
        "holdout",
        "label",
        "logit",
        "metric",
        "neighbor",
        "obligation",
        "outcome",
        "partition",
        "passed",
        "premise",
        "proof",
        "prover",
        "raw",
        "result",
        "retrieval",
        "reward",
        "solver",
        "source",
        "split",
        "status",
        "target",
        "test",
        "text",
        "theorem",
        "trace",
        "train",
        "validation",
        "verdict",
    }
)


def _feature_name(value: Any) -> str:
    name = _text(value, "feature_name")
    if not _FEATURE_NAME_RE.fullmatch(name):
        raise FormalizationValidationError(
            "feature names must be lowercase stable paths"
        )
    components = frozenset(filter(None, re.split(r"[^a-z0-9]+", name)))
    forbidden = sorted(components & _FORBIDDEN_COMPONENTS)
    if forbidden:
        raise FormalizationValidationError(
            "feature name contains leakage-prone component(s): "
            + ", ".join(forbidden)
        )
    return name


def _feature_value(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FormalizationValidationError(
            "formalization feature values must be numeric, not boolean"
        )
    result = float(value)
    if not math.isfinite(result):
        raise FormalizationValidationError(
            "formalization feature values must be finite"
        )
    return result


def _snapshot_ids(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)):
        raise FormalizationValidationError(
            "context_snapshot_ids must be a sequence"
        )
    normalized = tuple(values)
    if len(normalized) != len(set(normalized)):
        raise FormalizationValidationError(
            "context_snapshot_ids must be unique"
        )
    for value in normalized:
        if not isinstance(value, str) or not _SNAPSHOT_RE.fullmatch(value):
            raise FormalizationValidationError(
                "context snapshot IDs must be immutable stable identifiers"
            )
    return tuple(sorted(normalized))


@dataclass(frozen=True, slots=True)
class FormalizationFeatures:
    """One immutable sparse numeric vector.

    ``sample_id``, ``domain``, and ``declaration_digest`` are audit bindings;
    they are intentionally not returned by :attr:`model_input`.  Snapshot IDs
    bind immutable retrieval context and likewise are not model features.
    """

    sample_id: str
    domain: str
    declaration_digest: str
    feature_names: tuple[str, ...]
    feature_values: tuple[float, ...]
    extractor_id: str
    extractor_version: str
    context_snapshot_ids: tuple[str, ...] = ()
    schema_version: str = FORMALIZATION_FEATURES_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "sample_id", _identifier(self.sample_id, "sample_id")
        )
        object.__setattr__(self, "domain", _identifier(self.domain, "domain"))
        if (
            not isinstance(self.declaration_digest, str)
            or not _DIGEST_RE.fullmatch(self.declaration_digest)
        ):
            raise FormalizationValidationError(
                "declaration_digest must be a lowercase sha256:<hex> digest"
            )
        object.__setattr__(
            self, "extractor_id", _identifier(self.extractor_id, "extractor_id")
        )
        object.__setattr__(
            self,
            "extractor_version",
            _identifier(self.extractor_version, "extractor_version"),
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != FORMALIZATION_FEATURES_SCHEMA_VERSION:
            raise FormalizationValidationError(
                f"unsupported formalization features schema: {self.schema_version!r}"
            )
        if not isinstance(self.feature_names, tuple) or not isinstance(
            self.feature_values, tuple
        ):
            raise FormalizationValidationError(
                "feature_names and feature_values must be immutable tuples"
            )
        if not self.feature_names:
            raise FormalizationValidationError(
                "formalization features must contain at least one feature"
            )
        if len(self.feature_names) != len(self.feature_values):
            raise FormalizationValidationError(
                "feature_names and feature_values must have equal lengths"
            )
        if len(self.feature_names) > MAX_FORMALIZATION_FEATURES:
            raise FormalizationValidationError(
                f"formalization features exceed {MAX_FORMALIZATION_FEATURES} values"
            )
        names = tuple(_feature_name(item) for item in self.feature_names)
        if len(names) != len(set(names)):
            raise FormalizationValidationError("feature names must be unique")
        values = tuple(_feature_value(item) for item in self.feature_values)
        pairs = tuple(sorted(zip(names, values), key=lambda item: item[0]))
        object.__setattr__(self, "feature_names", tuple(name for name, _ in pairs))
        object.__setattr__(
            self, "feature_values", tuple(value for _, value in pairs)
        )
        object.__setattr__(
            self,
            "context_snapshot_ids",
            _snapshot_ids(self.context_snapshot_ids),
        )

    @classmethod
    def from_sample(
        cls,
        sample: FormalizationSample,
        features: Mapping[str, int | float],
        *,
        extractor_id: str,
        extractor_version: str,
        context_snapshot_ids: Sequence[str] = (),
    ) -> "FormalizationFeatures":
        """Bind an already-computed numeric vector to a validated sample."""

        if not isinstance(sample, FormalizationSample):
            raise FormalizationValidationError(
                "sample must be a FormalizationSample"
            )
        sample.validate()
        return cls.from_values(
            sample_id=sample.sample_id,
            domain=sample.domain,
            declaration_digest=sample.declaration_digest,
            features=features,
            extractor_id=extractor_id,
            extractor_version=extractor_version,
            context_snapshot_ids=context_snapshot_ids,
        )

    @classmethod
    def from_values(
        cls,
        *,
        sample_id: str,
        domain: str,
        declaration_digest: str,
        features: Mapping[str, int | float],
        extractor_id: str,
        extractor_version: str,
        context_snapshot_ids: Sequence[str] = (),
    ) -> "FormalizationFeatures":
        if not isinstance(features, Mapping):
            raise FormalizationValidationError("features must be a mapping")
        items = tuple(features.items())
        return cls(
            sample_id=sample_id,
            domain=domain,
            declaration_digest=declaration_digest,
            feature_names=tuple(name for name, _ in items),
            feature_values=tuple(value for _, value in items),
            extractor_id=extractor_id,
            extractor_version=extractor_version,
            context_snapshot_ids=tuple(context_snapshot_ids),
        )

    @property
    def feature_map(self) -> Mapping[str, float]:
        """Return an immutable name-to-value view."""

        return MappingProxyType(dict(zip(self.feature_names, self.feature_values)))

    @property
    def model_input(self) -> tuple[float, ...]:
        """Return only numeric values in canonical feature-name order."""

        return self.feature_values

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.to_dict(),
            domain="formalization-features",
            schema_version=self.schema_version,
        )

    @property
    def digest(self) -> str:
        return self.identity.digest

    def to_dict(self) -> dict[str, Any]:
        return {
            "context_snapshot_ids": list(self.context_snapshot_ids),
            "declaration_digest": self.declaration_digest,
            "domain": self.domain,
            "extractor_id": self.extractor_id,
            "extractor_version": self.extractor_version,
            "feature_names": list(self.feature_names),
            "feature_values": list(self.feature_values),
            "sample_id": self.sample_id,
            "schema_version": self.schema_version,
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FormalizationFeatures":
        value = _mapping(value, "formalization features")
        _reject_unknown(
            value,
            frozenset(
                {
                    "context_snapshot_ids",
                    "declaration_digest",
                    "domain",
                    "extractor_id",
                    "extractor_version",
                    "feature_names",
                    "feature_values",
                    "sample_id",
                    "schema_version",
                }
            ),
            "formalization features",
        )
        return cls(
            sample_id=value.get("sample_id", ""),
            domain=value.get("domain", ""),
            declaration_digest=value.get("declaration_digest", ""),
            feature_names=tuple(
                _sequence(value.get("feature_names", ()), "feature_names")
            ),
            feature_values=tuple(
                _sequence(value.get("feature_values", ()), "feature_values")
            ),
            extractor_id=value.get("extractor_id", ""),
            extractor_version=value.get("extractor_version", ""),
            context_snapshot_ids=tuple(
                _sequence(
                    value.get("context_snapshot_ids", ()),
                    "context_snapshot_ids",
                )
            ),
            schema_version=value.get(
                "schema_version", FORMALIZATION_FEATURES_SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_json(
        cls, value: str | bytes | bytearray
    ) -> "FormalizationFeatures":
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, UnicodeDecodeError) as exc:
            raise FormalizationValidationError(
                "formalization features must be valid JSON"
            ) from exc
        return cls.from_dict(_mapping(decoded, "formalization features"))


def build_formalization_features(
    sample: FormalizationSample,
    features: Mapping[str, int | float],
    *,
    extractor_id: str,
    extractor_version: str,
    context_snapshot_ids: Sequence[str] = (),
) -> FormalizationFeatures:
    """Functional spelling of :meth:`FormalizationFeatures.from_sample`."""

    return FormalizationFeatures.from_sample(
        sample,
        features,
        extractor_id=extractor_id,
        extractor_version=extractor_version,
        context_snapshot_ids=context_snapshot_ids,
    )


def validate_source_free_features(
    value: FormalizationFeatures | Mapping[str, Any],
) -> FormalizationFeatures:
    """Decode and validate a source-free feature artifact."""

    if isinstance(value, FormalizationFeatures):
        # Reconstruct to defend callers against objects produced by unsafe
        # deserialization or future subclassing.
        return FormalizationFeatures.from_dict(value.to_dict())
    return FormalizationFeatures.from_dict(value)


__all__ = [
    "FORMALIZATION_FEATURES_SCHEMA_VERSION",
    "MAX_FORMALIZATION_FEATURES",
    "FormalizationFeatures",
    "build_formalization_features",
    "validate_source_free_features",
]
