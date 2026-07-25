"""Domain-separated checkpoint manifests for learned formalization advisors.

Weights are opaque artifacts here.  A manifest records enough immutable
identity to decide whether a checkpoint may be used, but loading a model and
deciding whether its candidates are correct remain outside this module.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.identity import (
    CanonicalIdentity,
    canonical_identity,
)

from .samples import (
    FormalizationValidationError,
    _DIGEST_RE,
    _identifier,
    _mapping,
    _reject_unknown,
    _text,
)


CHECKPOINT_MANIFEST_SCHEMA_VERSION: Final = "formalization-checkpoint-manifest/v1"


def _digest(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise FormalizationValidationError(
            f"{field_name} must be a lowercase sha256:<hex> digest"
        )
    return value


def _domain_member(value: Any, *, domain: str, field_name: str) -> str:
    result = _identifier(value, field_name)
    if not result.startswith(f"{domain}:"):
        raise FormalizationValidationError(
            f"{field_name} must be namespaced under {domain!r}"
        )
    return result


@dataclass(frozen=True, slots=True)
class CheckpointManifest:
    """Immutable compatibility and lineage record for one advisor head.

    ``checkpoint_id`` and ``head_id`` must begin with ``"<domain>:"``.  This
    prevents a Legal, Security, or Intent head from being selected through a
    shared unqualified name even when the underlying encoder is transferable.
    """

    checkpoint_id: str
    domain: str
    head_id: str
    model_id: str
    model_version: str
    weights_digest: str
    training_config_identity: str
    ontology_identity: str
    view_registry_identity: str
    feature_schema_version: str
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = CHECKPOINT_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        domain = _identifier(self.domain, "domain")
        object.__setattr__(self, "domain", domain)
        object.__setattr__(
            self,
            "checkpoint_id",
            _domain_member(
                self.checkpoint_id,
                domain=domain,
                field_name="checkpoint_id",
            ),
        )
        object.__setattr__(
            self,
            "head_id",
            _domain_member(self.head_id, domain=domain, field_name="head_id"),
        )
        object.__setattr__(self, "model_id", _identifier(self.model_id, "model_id"))
        object.__setattr__(
            self,
            "model_version",
            _identifier(self.model_version, "model_version"),
        )
        for field_name in (
            "weights_digest",
            "training_config_identity",
            "ontology_identity",
            "view_registry_identity",
        ):
            object.__setattr__(
                self,
                field_name,
                _digest(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "feature_schema_version",
            _identifier(self.feature_schema_version, "feature_schema_version"),
        )
        object.__setattr__(
            self,
            "metadata",
            self.metadata
            if isinstance(self.metadata, FrozenMap)
            else FrozenMap(_mapping(self.metadata, "metadata")),
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != CHECKPOINT_MANIFEST_SCHEMA_VERSION:
            raise FormalizationValidationError(
                f"unsupported checkpoint manifest schema: {self.schema_version!r}"
            )

    @property
    def model_identity(self) -> str:
        """Identity of the exact model implementation and weights."""

        return canonical_identity(
            {
                "model_id": self.model_id,
                "model_version": self.model_version,
                "weights_digest": self.weights_digest,
            },
            domain="formalization-advisor-model",
            schema_version="formalization-advisor-model/v1",
        ).digest

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.to_dict(),
            domain=f"formalization-checkpoint:{self.domain}",
            schema_version=self.schema_version,
        )

    @property
    def digest(self) -> str:
        return self.identity.digest

    @property
    def cid(self) -> str:
        return self.identity.cid

    def require_compatible(
        self,
        *,
        domain: str,
        ontology_identity: str,
        view_registry_identity: str,
        feature_schema_version: str,
    ) -> "CheckpointManifest":
        """Fail closed unless every domain/schema dependency matches exactly."""

        expected = {
            "domain": _identifier(domain, "domain"),
            "ontology_identity": _digest(
                ontology_identity, "ontology_identity"
            ),
            "view_registry_identity": _digest(
                view_registry_identity, "view_registry_identity"
            ),
            "feature_schema_version": _identifier(
                feature_schema_version, "feature_schema_version"
            ),
        }
        mismatches = [
            name
            for name, wanted in expected.items()
            if getattr(self, name) != wanted
        ]
        if mismatches:
            raise FormalizationValidationError(
                "checkpoint is incompatible with "
                + ", ".join(sorted(mismatches))
            )
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "domain": self.domain,
            "feature_schema_version": self.feature_schema_version,
            "head_id": self.head_id,
            "metadata": self.metadata.to_dict(),
            "model_id": self.model_id,
            "model_version": self.model_version,
            "ontology_identity": self.ontology_identity,
            "schema_version": self.schema_version,
            "training_config_identity": self.training_config_identity,
            "view_registry_identity": self.view_registry_identity,
            "weights_digest": self.weights_digest,
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
    def from_dict(cls, value: Mapping[str, Any]) -> "CheckpointManifest":
        value = _mapping(value, "checkpoint manifest")
        _reject_unknown(
            value,
            frozenset(
                {
                    "checkpoint_id",
                    "domain",
                    "feature_schema_version",
                    "head_id",
                    "metadata",
                    "model_id",
                    "model_version",
                    "ontology_identity",
                    "schema_version",
                    "training_config_identity",
                    "view_registry_identity",
                    "weights_digest",
                }
            ),
            "checkpoint manifest",
        )
        return cls(
            checkpoint_id=value.get("checkpoint_id", ""),
            domain=value.get("domain", ""),
            head_id=value.get("head_id", ""),
            model_id=value.get("model_id", ""),
            model_version=value.get("model_version", ""),
            weights_digest=value.get("weights_digest", ""),
            training_config_identity=value.get("training_config_identity", ""),
            ontology_identity=value.get("ontology_identity", ""),
            view_registry_identity=value.get("view_registry_identity", ""),
            feature_schema_version=value.get("feature_schema_version", ""),
            metadata=FrozenMap(_mapping(value.get("metadata", {}), "metadata")),
            schema_version=value.get(
                "schema_version", CHECKPOINT_MANIFEST_SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_json(
        cls, value: str | bytes | bytearray
    ) -> "CheckpointManifest":
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, UnicodeDecodeError) as exc:
            raise FormalizationValidationError(
                "checkpoint manifest must be valid JSON"
            ) from exc
        return cls.from_dict(_mapping(decoded, "checkpoint manifest"))


def validate_checkpoint_manifest(
    value: CheckpointManifest | Mapping[str, Any],
) -> CheckpointManifest:
    """Return a defensively reconstructed checkpoint manifest."""

    if isinstance(value, CheckpointManifest):
        return CheckpointManifest.from_dict(value.to_dict())
    return CheckpointManifest.from_dict(value)


__all__ = [
    "CHECKPOINT_MANIFEST_SCHEMA_VERSION",
    "CheckpointManifest",
    "validate_checkpoint_manifest",
]
