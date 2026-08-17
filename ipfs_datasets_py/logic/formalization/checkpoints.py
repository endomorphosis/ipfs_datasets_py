"""Domain-separated checkpoint manifests for learned formalization advisors.

Weights are opaque artifacts here.  A manifest records enough immutable
identity to decide whether a checkpoint may be used, but loading a model and
deciding whether its candidates are correct remain outside this module.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
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
        raise FormalizationValidationError(f"{field_name} must be a lowercase sha256:<hex> digest")
    return value


def _domain_member(value: Any, *, domain: str, field_name: str) -> str:
    result = _identifier(value, field_name)
    if not result.startswith(f"{domain}:"):
        raise FormalizationValidationError(f"{field_name} must be namespaced under {domain!r}")
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
            "ontology_identity": _digest(ontology_identity, "ontology_identity"),
            "view_registry_identity": _digest(view_registry_identity, "view_registry_identity"),
            "feature_schema_version": _identifier(feature_schema_version, "feature_schema_version"),
        }
        mismatches = [name for name, wanted in expected.items() if getattr(self, name) != wanted]
        if mismatches:
            raise FormalizationValidationError(
                "checkpoint is incompatible with " + ", ".join(sorted(mismatches))
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
            schema_version=value.get("schema_version", CHECKPOINT_MANIFEST_SCHEMA_VERSION),
        )

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> "CheckpointManifest":
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, UnicodeDecodeError) as exc:
            raise FormalizationValidationError("checkpoint manifest must be valid JSON") from exc
        return cls.from_dict(_mapping(decoded, "checkpoint manifest"))


def validate_checkpoint_manifest(
    value: CheckpointManifest | Mapping[str, Any],
) -> CheckpointManifest:
    """Return a defensively reconstructed checkpoint manifest."""

    if isinstance(value, CheckpointManifest):
        return CheckpointManifest.from_dict(value.to_dict())
    return CheckpointManifest.from_dict(value)


IR_CHECKPOINT_MANIFEST_SCHEMA: Final = "IRCheckpointManifest@1"
IR_PROMOTION_MANIFEST_SCHEMA: Final = "IRPromotionManifest@1"
IR_CHECKPOINT_SIDE_OUTCOME_SCHEMA: Final = "IRCheckpointSideOutcome@1"
IR_CHECKPOINT_POINTER_SCHEMA: Final = "IRCheckpointPointer@1"
IR_CHECKPOINT_LIFECYCLE_SCHEMA: Final = "IRCheckpointLifecycle@1"

FORMALIZATION_ADVISOR_LEGACY_KIND: Final = CHECKPOINT_MANIFEST_SCHEMA_VERSION
MODAL_STATE_LEGACY_KIND: Final = "modal-autoencoder-checkpoint-v1"

IR_CHECKPOINT_ID_PREFIX: Final = "ir:checkpoint:"
IR_PROMOTION_ID_PREFIX: Final = "ir:promotion:"

IR_CHECKPOINT_SOURCE_KINDS: Final[tuple[str, ...]] = (
    "semantic",
    "adapted_formalization_advisor",
    "adapted_modal_state",
)

IR_CHECKPOINT_LIFECYCLE_STATES: Final[tuple[str, ...]] = (
    "created",
    "persisted",
    "trained",
    "evaluated",
    "candidate",
    "admitted",
    "promoted",
    "rejected",
    "quarantined",
    "rolled_back",
    "superseded",
)

IR_CHECKPOINT_TERMINAL_STATES: Final[frozenset[str]] = frozenset(
    {"rejected", "quarantined", "rolled_back", "superseded"}
)

IR_CHECKPOINT_LIFECYCLE_TRANSITIONS: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("created", "persisted"),
        ("persisted", "trained"),
        ("trained", "evaluated"),
        ("evaluated", "candidate"),
        ("evaluated", "rejected"),
        ("candidate", "admitted"),
        ("candidate", "rejected"),
        ("admitted", "promoted"),
        ("admitted", "rejected"),
        ("promoted", "superseded"),
        ("promoted", "rolled_back"),
    }
)

IR_CHECKPOINT_SIDE_OUTCOME_KINDS: Final[tuple[str, ...]] = (
    "current_pointer",
    "quarantine_receipt",
    "promotion_receipt",
    "rejection_receipt",
    "rollback_receipt",
    "supersession_receipt",
    "recovery_receipt",
    "compatibility_adapter_receipt",
)

IR_PROMOTION_DECISIONS: Final[tuple[str, ...]] = (
    "promote",
    "reject",
    "regressed",
    "inconclusive",
)

IR_PROMOTION_REQUIRED_GATES: Final[tuple[str, ...]] = (
    "lineage",
    "syntax",
    "type",
    "semantic",
    "proof",
    "calibration",
    "family",
    "jurisdiction",
    "source_span",
    "latency",
    "resource",
)

IR_CHECKPOINT_M1_IDENTITY_FIELDS: Final[tuple[str, ...]] = (
    "architecture_identity",
    "tokenizer_identity",
    "vocabulary_identity",
    "corpus_root",
    "split_root",
    "curriculum_identity",
    "loss_configuration_identity",
    "optimizer_identity",
    "scheduler_identity",
    "data_cursor",
    "random_state",
    "environment_identity",
    "code_identity",
    "compiler_identity",
    "decompiler_identity",
    "campaign_identity",
    "training_config_identity",
    "ontology_identity",
    "view_registry_identity",
    "state_digest",
    "weights_digest",
    "metric_lineage_digest",
    "legacy_manifest_digest",
)

IR_CHECKPOINT_M1_FIELDS: Final[tuple[str, ...]] = (
    "schema_version",
    "checkpoint_id",
    "lifecycle_state",
    "source_kind",
    "parent_checkpoint_id",
    "feature_schema_version",
    "state_schema_version",
    "revision",
    "authority",
    "legacy_manifest_kind",
    *IR_CHECKPOINT_M1_IDENTITY_FIELDS,
    "artifact_identities",
    "side_outcomes",
)

IR_CHECKPOINT_ARTIFACT_IDENTITY_KEYS: Final[tuple[str, ...]] = IR_CHECKPOINT_M1_IDENTITY_FIELDS


def _closed_member(value: Any, *, allowed: Sequence[str], field_name: str) -> str:
    result = _text(value, field_name)
    if result not in allowed:
        raise FormalizationValidationError(
            f"{field_name} must be one of {', '.join(allowed)}; got {result!r}"
        )
    return result


def _optional_identifier(value: Any, field_name: str) -> str:
    if value is None or value == "":
        return ""
    return _identifier(value, field_name)


def _namespaced_id(value: Any, *, prefix: str, field_name: str) -> str:
    result = _identifier(value, field_name)
    if not result.startswith(prefix):
        raise FormalizationValidationError(f"{field_name} must begin with {prefix!r}")
    return result


def _bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise FormalizationValidationError(f"{field_name} must be a boolean")
    return value


def _non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise FormalizationValidationError(f"{field_name} must be a non-negative integer")
    if value < 0:
        raise FormalizationValidationError(f"{field_name} must be a non-negative integer")
    return value


def _unique_closed(
    values: Any, *, allowed: Sequence[str], field_name: str
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise FormalizationValidationError(f"{field_name} must be a sequence")
    normalized = tuple(
        _closed_member(item, allowed=allowed, field_name=field_name) for item in values
    )
    if len(normalized) != len(set(normalized)):
        raise FormalizationValidationError(f"{field_name} values must be unique")
    return normalized


class IRCheckpointValidationError(FormalizationValidationError):
    """Raised when a semantic checkpoint or promotion contract is invalid."""


class IRCheckpointLifecycleError(IRCheckpointValidationError):
    """Raised when a lifecycle transition is illegal."""


class IRCheckpointPromotionError(IRCheckpointValidationError):
    """Raised when promotion is refused by policy."""


def _require_complete_artifact_identities(
    identities: Mapping[str, Any],
    *,
    expected: Mapping[str, str],
) -> FrozenMap:
    payload = {
        str(key): _digest(value, f"artifact_identities.{key}")
        for key, value in identities.items()
    }
    missing = [name for name in IR_CHECKPOINT_ARTIFACT_IDENTITY_KEYS if name not in payload]
    if missing:
        raise IRCheckpointValidationError(
            "artifact identities incomplete: " + ", ".join(missing)
        )
    extra = sorted(set(payload) - set(IR_CHECKPOINT_ARTIFACT_IDENTITY_KEYS))
    if extra:
        raise IRCheckpointValidationError(
            "unknown artifact identity field(s): " + ", ".join(extra)
        )
    mismatches = sorted(
        name for name, wanted in expected.items() if payload.get(name) != wanted
    )
    if mismatches:
        raise IRCheckpointValidationError(
            "artifact identities do not match M1 fields: " + ", ".join(mismatches)
        )
    return FrozenMap(payload)


def complete_artifact_identities(values: Mapping[str, Any]) -> dict[str, str]:
    """Return the closed M1 artifact-identity map from a field mapping."""

    return {
        name: _digest(values[name], name)
        for name in IR_CHECKPOINT_ARTIFACT_IDENTITY_KEYS
    }


@dataclass(frozen=True, slots=True)
class IRCheckpointSideOutcome:
    """One closed side outcome of a checkpoint lifecycle step."""

    kind: str
    subject_checkpoint_id: str
    related_checkpoint_id: str = ""
    reason: str = ""
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = IR_CHECKPOINT_SIDE_OUTCOME_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "kind",
            _closed_member(
                self.kind,
                allowed=IR_CHECKPOINT_SIDE_OUTCOME_KINDS,
                field_name="kind",
            ),
        )
        object.__setattr__(
            self,
            "subject_checkpoint_id",
            _namespaced_id(
                self.subject_checkpoint_id,
                prefix=IR_CHECKPOINT_ID_PREFIX,
                field_name="subject_checkpoint_id",
            ),
        )
        related = _optional_identifier(self.related_checkpoint_id, "related_checkpoint_id")
        if related and not related.startswith(IR_CHECKPOINT_ID_PREFIX):
            raise IRCheckpointValidationError(
                "related_checkpoint_id must begin with "
                f"{IR_CHECKPOINT_ID_PREFIX!r} when present"
            )
        object.__setattr__(self, "related_checkpoint_id", related)
        object.__setattr__(self, "reason", _text(self.reason, "reason") if self.reason else "")
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
        if self.schema_version != IR_CHECKPOINT_SIDE_OUTCOME_SCHEMA:
            raise IRCheckpointValidationError(
                f"unsupported side-outcome schema: {self.schema_version!r}"
            )

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.to_dict(),
            domain="ir-checkpoint-side-outcome",
            schema_version=self.schema_version,
        )

    @property
    def digest(self) -> str:
        return self.identity.digest

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "metadata": self.metadata.to_dict(),
            "reason": self.reason,
            "related_checkpoint_id": self.related_checkpoint_id,
            "schema_version": self.schema_version,
            "subject_checkpoint_id": self.subject_checkpoint_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "IRCheckpointSideOutcome":
        value = _mapping(value, "checkpoint side outcome")
        _reject_unknown(
            value,
            frozenset(
                {
                    "kind",
                    "metadata",
                    "reason",
                    "related_checkpoint_id",
                    "schema_version",
                    "subject_checkpoint_id",
                }
            ),
            "checkpoint side outcome",
        )
        return cls(
            kind=value.get("kind", ""),
            subject_checkpoint_id=value.get("subject_checkpoint_id", ""),
            related_checkpoint_id=value.get("related_checkpoint_id", ""),
            reason=value.get("reason", ""),
            metadata=FrozenMap(_mapping(value.get("metadata", {}), "metadata")),
            schema_version=value.get("schema_version", IR_CHECKPOINT_SIDE_OUTCOME_SCHEMA),
        )


def _parse_side_outcomes(value: Any) -> tuple[IRCheckpointSideOutcome, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise IRCheckpointValidationError("side_outcomes must be a sequence")
    outcomes = tuple(
        item
        if isinstance(item, IRCheckpointSideOutcome)
        else IRCheckpointSideOutcome.from_dict(_mapping(item, "side outcome"))
        for item in value
    )
    digests = [item.digest for item in outcomes]
    if len(digests) != len(set(digests)):
        raise IRCheckpointValidationError("side_outcomes must be unique")
    return outcomes


def allowed_lifecycle_transition(current: str, nxt: str) -> bool:
    """Return whether ``current -> nxt`` is an admitted closed transition."""

    current_state = _closed_member(
        current, allowed=IR_CHECKPOINT_LIFECYCLE_STATES, field_name="lifecycle_state"
    )
    next_state = _closed_member(
        nxt, allowed=IR_CHECKPOINT_LIFECYCLE_STATES, field_name="next_lifecycle_state"
    )
    if next_state == "quarantined" and current_state != "quarantined":
        return True
    return (current_state, next_state) in IR_CHECKPOINT_LIFECYCLE_TRANSITIONS


def verify_lifecycle_transition(current: str, nxt: str) -> tuple[str, str]:
    """Fail closed unless the transition is in the closed lifecycle table."""

    if not allowed_lifecycle_transition(current, nxt):
        raise IRCheckpointLifecycleError(
            f"illegal lifecycle transition: {current!r} -> {nxt!r}"
        )
    return current, nxt


@dataclass(frozen=True, slots=True)
class IRCheckpointManifest:
    """Unified semantic checkpoint identity.  Legacy manifests stay separate.

    Artifact identity is independent of lifecycle state and side outcomes so a
    promotion cannot rewrite the model identity.  ``authority`` is never true
    for an unpromoted record and is never granted by the checkpoint itself.
    """

    checkpoint_id: str
    architecture_identity: str
    tokenizer_identity: str
    vocabulary_identity: str
    corpus_root: str
    split_root: str
    curriculum_identity: str
    loss_configuration_identity: str
    optimizer_identity: str
    scheduler_identity: str
    data_cursor: str
    random_state: str
    environment_identity: str
    code_identity: str
    compiler_identity: str
    decompiler_identity: str
    campaign_identity: str
    training_config_identity: str
    ontology_identity: str
    view_registry_identity: str
    feature_schema_version: str
    state_schema_version: str
    state_digest: str
    weights_digest: str
    metric_lineage_digest: str
    revision: int = 0
    lifecycle_state: str = "created"
    source_kind: str = "semantic"
    parent_checkpoint_id: str = ""
    authority: bool = False
    legacy_manifest_kind: str = ""
    legacy_manifest_digest: str = "sha256:" + ("0" * 64)
    artifact_identities: FrozenMap = field(default_factory=FrozenMap)
    side_outcomes: tuple[IRCheckpointSideOutcome, ...] = ()
    schema_version: str = IR_CHECKPOINT_MANIFEST_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != IR_CHECKPOINT_MANIFEST_SCHEMA:
            raise IRCheckpointValidationError(
                f"unsupported semantic checkpoint schema: {self.schema_version!r}"
            )
        object.__setattr__(
            self,
            "checkpoint_id",
            _namespaced_id(
                self.checkpoint_id,
                prefix=IR_CHECKPOINT_ID_PREFIX,
                field_name="checkpoint_id",
            ),
        )
        parent = _optional_identifier(self.parent_checkpoint_id, "parent_checkpoint_id")
        if parent:
            if not parent.startswith(IR_CHECKPOINT_ID_PREFIX):
                raise IRCheckpointValidationError(
                    "parent_checkpoint_id must begin with "
                    f"{IR_CHECKPOINT_ID_PREFIX!r} when present"
                )
            if parent == self.checkpoint_id:
                raise IRCheckpointValidationError("checkpoint cannot parent itself")
        object.__setattr__(self, "parent_checkpoint_id", parent)
        object.__setattr__(
            self,
            "lifecycle_state",
            _closed_member(
                self.lifecycle_state,
                allowed=IR_CHECKPOINT_LIFECYCLE_STATES,
                field_name="lifecycle_state",
            ),
        )
        object.__setattr__(
            self,
            "source_kind",
            _closed_member(
                self.source_kind,
                allowed=IR_CHECKPOINT_SOURCE_KINDS,
                field_name="source_kind",
            ),
        )
        object.__setattr__(
            self,
            "feature_schema_version",
            _identifier(self.feature_schema_version, "feature_schema_version"),
        )
        object.__setattr__(
            self,
            "state_schema_version",
            _identifier(self.state_schema_version, "state_schema_version"),
        )
        object.__setattr__(self, "revision", _non_negative_int(self.revision, "revision"))
        object.__setattr__(self, "authority", _bool(self.authority, "authority"))
        if self.authority and self.lifecycle_state != "promoted":
            raise IRCheckpointValidationError(
                "authority is admitted only for a promoted checkpoint"
            )
        if self.lifecycle_state == "promoted" and not self.authority:
            raise IRCheckpointValidationError(
                "a promoted checkpoint must record admitted authority"
            )
        kind = self.legacy_manifest_kind
        object.__setattr__(
            self,
            "legacy_manifest_kind",
            _identifier(kind, "legacy_manifest_kind") if kind else "",
        )
        if self.source_kind == "semantic" and self.legacy_manifest_kind:
            raise IRCheckpointValidationError(
                "semantic checkpoints must not alias a legacy manifest kind"
            )
        if self.source_kind != "semantic" and not self.legacy_manifest_kind:
            raise IRCheckpointValidationError(
                "adapted checkpoints must name the separate legacy manifest kind"
            )
        if self.legacy_manifest_kind in {
            IR_CHECKPOINT_MANIFEST_SCHEMA,
            IR_PROMOTION_MANIFEST_SCHEMA,
        }:
            raise IRCheckpointValidationError(
                "legacy manifest kind cannot alias the semantic checkpoint schema"
            )
        for name in IR_CHECKPOINT_M1_IDENTITY_FIELDS:
            object.__setattr__(self, name, _digest(getattr(self, name), name))
        identities = (
            self.artifact_identities
            if isinstance(self.artifact_identities, FrozenMap)
            and set(self.artifact_identities) == set(IR_CHECKPOINT_ARTIFACT_IDENTITY_KEYS)
            else complete_artifact_identities(
                {name: getattr(self, name) for name in IR_CHECKPOINT_M1_IDENTITY_FIELDS}
            )
        )
        object.__setattr__(
            self,
            "artifact_identities",
            _require_complete_artifact_identities(
                identities
                if isinstance(identities, Mapping)
                else identities.to_dict(),
                expected={
                    name: getattr(self, name) for name in IR_CHECKPOINT_M1_IDENTITY_FIELDS
                },
            ),
        )
        object.__setattr__(self, "side_outcomes", _parse_side_outcomes(self.side_outcomes))
        for outcome in self.side_outcomes:
            if outcome.subject_checkpoint_id != self.checkpoint_id:
                raise IRCheckpointValidationError(
                    "side outcome subject must match checkpoint_id"
                )

    def artifact_payload(self) -> dict[str, Any]:
        """Return the M1 identity payload, excluding lifecycle side state."""

        payload = {
            "architecture_identity": self.architecture_identity,
            "campaign_identity": self.campaign_identity,
            "checkpoint_id": self.checkpoint_id,
            "code_identity": self.code_identity,
            "compiler_identity": self.compiler_identity,
            "corpus_root": self.corpus_root,
            "curriculum_identity": self.curriculum_identity,
            "data_cursor": self.data_cursor,
            "decompiler_identity": self.decompiler_identity,
            "environment_identity": self.environment_identity,
            "feature_schema_version": self.feature_schema_version,
            "legacy_manifest_digest": self.legacy_manifest_digest,
            "legacy_manifest_kind": self.legacy_manifest_kind,
            "loss_configuration_identity": self.loss_configuration_identity,
            "metric_lineage_digest": self.metric_lineage_digest,
            "ontology_identity": self.ontology_identity,
            "optimizer_identity": self.optimizer_identity,
            "parent_checkpoint_id": self.parent_checkpoint_id,
            "random_state": self.random_state,
            "revision": self.revision,
            "scheduler_identity": self.scheduler_identity,
            "schema_version": self.schema_version,
            "source_kind": self.source_kind,
            "split_root": self.split_root,
            "state_digest": self.state_digest,
            "state_schema_version": self.state_schema_version,
            "tokenizer_identity": self.tokenizer_identity,
            "training_config_identity": self.training_config_identity,
            "view_registry_identity": self.view_registry_identity,
            "vocabulary_identity": self.vocabulary_identity,
            "weights_digest": self.weights_digest,
        }
        return payload

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.artifact_payload(),
            domain="ir-checkpoint-manifest",
            schema_version=self.schema_version,
        )

    @property
    def digest(self) -> str:
        return self.identity.digest

    @property
    def cid(self) -> str:
        return self.identity.cid

    @property
    def record_identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.to_dict(),
            domain="ir-checkpoint-record",
            schema_version=IR_CHECKPOINT_LIFECYCLE_SCHEMA,
        )

    @property
    def record_digest(self) -> str:
        return self.record_identity.digest

    def with_lifecycle(
        self,
        lifecycle_state: str,
        *,
        authority: bool | None = None,
        side_outcomes: Sequence[IRCheckpointSideOutcome] | None = None,
    ) -> "IRCheckpointManifest":
        """Return the same artifact with an admitted lifecycle mutation."""

        verify_lifecycle_transition(self.lifecycle_state, lifecycle_state)
        next_authority = (
            lifecycle_state == "promoted" if authority is None else bool(authority)
        )
        extra = () if side_outcomes is None else tuple(side_outcomes)
        merged = list(self.side_outcomes)
        seen = {item.digest for item in merged}
        for outcome in extra:
            parsed = (
                outcome
                if isinstance(outcome, IRCheckpointSideOutcome)
                else IRCheckpointSideOutcome.from_dict(outcome)
            )
            if parsed.digest not in seen:
                merged.append(parsed)
                seen.add(parsed.digest)
        payload = self.to_dict()
        payload["lifecycle_state"] = lifecycle_state
        payload["authority"] = next_authority
        payload["side_outcomes"] = [item.to_dict() for item in merged]
        return IRCheckpointManifest.from_dict(payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "architecture_identity": self.architecture_identity,
            "artifact_identities": self.artifact_identities.to_dict(),
            "authority": self.authority,
            "campaign_identity": self.campaign_identity,
            "checkpoint_id": self.checkpoint_id,
            "code_identity": self.code_identity,
            "compiler_identity": self.compiler_identity,
            "corpus_root": self.corpus_root,
            "curriculum_identity": self.curriculum_identity,
            "data_cursor": self.data_cursor,
            "decompiler_identity": self.decompiler_identity,
            "environment_identity": self.environment_identity,
            "feature_schema_version": self.feature_schema_version,
            "legacy_manifest_digest": self.legacy_manifest_digest,
            "legacy_manifest_kind": self.legacy_manifest_kind,
            "lifecycle_state": self.lifecycle_state,
            "loss_configuration_identity": self.loss_configuration_identity,
            "metric_lineage_digest": self.metric_lineage_digest,
            "ontology_identity": self.ontology_identity,
            "optimizer_identity": self.optimizer_identity,
            "parent_checkpoint_id": self.parent_checkpoint_id,
            "random_state": self.random_state,
            "revision": self.revision,
            "scheduler_identity": self.scheduler_identity,
            "schema_version": self.schema_version,
            "side_outcomes": [item.to_dict() for item in self.side_outcomes],
            "source_kind": self.source_kind,
            "split_root": self.split_root,
            "state_digest": self.state_digest,
            "state_schema_version": self.state_schema_version,
            "tokenizer_identity": self.tokenizer_identity,
            "training_config_identity": self.training_config_identity,
            "view_registry_identity": self.view_registry_identity,
            "vocabulary_identity": self.vocabulary_identity,
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
    def from_dict(cls, value: Mapping[str, Any]) -> "IRCheckpointManifest":
        value = _mapping(value, "IR checkpoint manifest")
        schema = str(value.get("schema_version") or "")
        if schema in {CHECKPOINT_MANIFEST_SCHEMA_VERSION, MODAL_STATE_LEGACY_KIND}:
            raise IRCheckpointValidationError(
                "incompatible manifest aliasing: legacy checkpoint manifests "
                "cannot be treated as IRCheckpointManifest@1"
            )
        _reject_unknown(value, frozenset(IR_CHECKPOINT_M1_FIELDS), "IR checkpoint manifest")
        return cls(
            checkpoint_id=value.get("checkpoint_id", ""),
            architecture_identity=value.get("architecture_identity", ""),
            tokenizer_identity=value.get("tokenizer_identity", ""),
            vocabulary_identity=value.get("vocabulary_identity", ""),
            corpus_root=value.get("corpus_root", ""),
            split_root=value.get("split_root", ""),
            curriculum_identity=value.get("curriculum_identity", ""),
            loss_configuration_identity=value.get("loss_configuration_identity", ""),
            optimizer_identity=value.get("optimizer_identity", ""),
            scheduler_identity=value.get("scheduler_identity", ""),
            data_cursor=value.get("data_cursor", ""),
            random_state=value.get("random_state", ""),
            environment_identity=value.get("environment_identity", ""),
            code_identity=value.get("code_identity", ""),
            compiler_identity=value.get("compiler_identity", ""),
            decompiler_identity=value.get("decompiler_identity", ""),
            campaign_identity=value.get("campaign_identity", ""),
            training_config_identity=value.get("training_config_identity", ""),
            ontology_identity=value.get("ontology_identity", ""),
            view_registry_identity=value.get("view_registry_identity", ""),
            feature_schema_version=value.get("feature_schema_version", ""),
            state_schema_version=value.get("state_schema_version", ""),
            state_digest=value.get("state_digest", ""),
            weights_digest=value.get("weights_digest", ""),
            metric_lineage_digest=value.get("metric_lineage_digest", ""),
            revision=value.get("revision", 0),
            lifecycle_state=value.get("lifecycle_state", "created"),
            source_kind=value.get("source_kind", "semantic"),
            parent_checkpoint_id=value.get("parent_checkpoint_id", ""),
            authority=value.get("authority", False),
            legacy_manifest_kind=value.get("legacy_manifest_kind", ""),
            legacy_manifest_digest=value.get(
                "legacy_manifest_digest", "sha256:" + ("0" * 64)
            ),
            artifact_identities=value.get("artifact_identities", {}),
            side_outcomes=value.get("side_outcomes", ()),
            schema_version=value.get("schema_version", IR_CHECKPOINT_MANIFEST_SCHEMA),
        )

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> "IRCheckpointManifest":
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, UnicodeDecodeError) as exc:
            raise IRCheckpointValidationError(
                "IR checkpoint manifest must be valid JSON"
            ) from exc
        return cls.from_dict(_mapping(decoded, "IR checkpoint manifest"))


def validate_ir_checkpoint_manifest(
    value: IRCheckpointManifest | Mapping[str, Any],
) -> IRCheckpointManifest:
    """Return a defensively reconstructed semantic checkpoint manifest."""

    if isinstance(value, IRCheckpointManifest):
        return IRCheckpointManifest.from_dict(value.to_dict())
    return IRCheckpointManifest.from_dict(value)


verify_ir_checkpoint_manifest = validate_ir_checkpoint_manifest


def adapt_formalization_advisor_manifest(
    manifest: CheckpointManifest | Mapping[str, Any],
    *,
    identities: Mapping[str, Any],
    checkpoint_id: str,
    parent_checkpoint_id: str = "",
    revision: int = 0,
    lifecycle_state: str = "created",
) -> IRCheckpointManifest:
    """Project an advisor compatibility manifest into IRCheckpointManifest@1.

    The legacy formalization schema remains a distinct document.  This adapter
    never aliases that document as the semantic checkpoint schema.
    """

    legacy = validate_checkpoint_manifest(manifest)
    supplied = dict(identities)
    supplied.setdefault("training_config_identity", legacy.training_config_identity)
    supplied.setdefault("ontology_identity", legacy.ontology_identity)
    supplied.setdefault("view_registry_identity", legacy.view_registry_identity)
    supplied.setdefault("weights_digest", legacy.weights_digest)
    supplied["legacy_manifest_digest"] = legacy.digest
    outcome = IRCheckpointSideOutcome(
        kind="compatibility_adapter_receipt",
        subject_checkpoint_id=checkpoint_id,
        reason="adapted formalization advisor manifest without schema aliasing",
        metadata=FrozenMap(
            {
                "legacy_checkpoint_id": legacy.checkpoint_id,
                "legacy_domain": legacy.domain,
                "legacy_head_id": legacy.head_id,
                "legacy_model_id": legacy.model_id,
                "legacy_schema": legacy.schema_version,
            }
        ),
    )
    return IRCheckpointManifest(
        checkpoint_id=checkpoint_id,
        parent_checkpoint_id=parent_checkpoint_id,
        lifecycle_state=lifecycle_state,
        source_kind="adapted_formalization_advisor",
        feature_schema_version=legacy.feature_schema_version,
        state_schema_version=supplied.get(
            "state_schema_version", "formalization-advisor-opaque-weights/v1"
        ),
        revision=revision,
        authority=False,
        legacy_manifest_kind=legacy.schema_version,
        architecture_identity=supplied["architecture_identity"],
        tokenizer_identity=supplied["tokenizer_identity"],
        vocabulary_identity=supplied["vocabulary_identity"],
        corpus_root=supplied["corpus_root"],
        split_root=supplied["split_root"],
        curriculum_identity=supplied["curriculum_identity"],
        loss_configuration_identity=supplied["loss_configuration_identity"],
        optimizer_identity=supplied["optimizer_identity"],
        scheduler_identity=supplied["scheduler_identity"],
        data_cursor=supplied["data_cursor"],
        random_state=supplied["random_state"],
        environment_identity=supplied["environment_identity"],
        code_identity=supplied["code_identity"],
        compiler_identity=supplied["compiler_identity"],
        decompiler_identity=supplied["decompiler_identity"],
        campaign_identity=supplied["campaign_identity"],
        training_config_identity=supplied["training_config_identity"],
        ontology_identity=supplied["ontology_identity"],
        view_registry_identity=supplied["view_registry_identity"],
        state_digest=supplied["state_digest"],
        weights_digest=supplied["weights_digest"],
        metric_lineage_digest=supplied["metric_lineage_digest"],
        legacy_manifest_digest=supplied["legacy_manifest_digest"],
        side_outcomes=(outcome,),
    )


@dataclass(frozen=True, slots=True)
class IRPromotionManifest:
    """Compare-and-swap promotion decision.  Never self- or loss-only promotion."""

    promotion_id: str
    candidate_checkpoint_id: str
    baseline_checkpoint_id: str
    expected_current_pointer: str
    actor_identity: str
    policy_identity: str
    evaluation_report_identity: str
    proof_evidence_identity: str
    admitted_gates: tuple[str, ...]
    decision: str
    reason: str
    human_approval_identity: str = ""
    loss_only: bool = False
    self_promotion: bool = False
    schema_version: str = IR_PROMOTION_MANIFEST_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != IR_PROMOTION_MANIFEST_SCHEMA:
            raise IRCheckpointValidationError(
                f"unsupported promotion manifest schema: {self.schema_version!r}"
            )
        object.__setattr__(
            self,
            "promotion_id",
            _namespaced_id(
                self.promotion_id,
                prefix=IR_PROMOTION_ID_PREFIX,
                field_name="promotion_id",
            ),
        )
        object.__setattr__(
            self,
            "candidate_checkpoint_id",
            _namespaced_id(
                self.candidate_checkpoint_id,
                prefix=IR_CHECKPOINT_ID_PREFIX,
                field_name="candidate_checkpoint_id",
            ),
        )
        object.__setattr__(
            self,
            "baseline_checkpoint_id",
            _namespaced_id(
                self.baseline_checkpoint_id,
                prefix=IR_CHECKPOINT_ID_PREFIX,
                field_name="baseline_checkpoint_id",
            ),
        )
        expected = _optional_identifier(
            self.expected_current_pointer, "expected_current_pointer"
        )
        if expected and not expected.startswith(IR_CHECKPOINT_ID_PREFIX):
            raise IRCheckpointValidationError(
                "expected_current_pointer must begin with "
                f"{IR_CHECKPOINT_ID_PREFIX!r} when present"
            )
        object.__setattr__(self, "expected_current_pointer", expected)
        object.__setattr__(self, "actor_identity", _digest(self.actor_identity, "actor_identity"))
        object.__setattr__(
            self, "policy_identity", _digest(self.policy_identity, "policy_identity")
        )
        object.__setattr__(
            self,
            "evaluation_report_identity",
            _digest(self.evaluation_report_identity, "evaluation_report_identity"),
        )
        object.__setattr__(
            self,
            "proof_evidence_identity",
            _digest(self.proof_evidence_identity, "proof_evidence_identity"),
        )
        approval = self.human_approval_identity
        object.__setattr__(
            self,
            "human_approval_identity",
            _digest(approval, "human_approval_identity") if approval else "",
        )
        object.__setattr__(
            self,
            "admitted_gates",
            _unique_closed(
                self.admitted_gates,
                allowed=IR_PROMOTION_REQUIRED_GATES,
                field_name="admitted_gates",
            ),
        )
        object.__setattr__(
            self,
            "decision",
            _closed_member(
                self.decision, allowed=IR_PROMOTION_DECISIONS, field_name="decision"
            ),
        )
        object.__setattr__(self, "reason", _text(self.reason, "reason"))
        object.__setattr__(self, "loss_only", _bool(self.loss_only, "loss_only"))
        object.__setattr__(
            self, "self_promotion", _bool(self.self_promotion, "self_promotion")
        )
        if self.candidate_checkpoint_id == self.baseline_checkpoint_id:
            object.__setattr__(self, "self_promotion", True)
        if self.loss_only and self.decision == "promote":
            raise IRCheckpointPromotionError("loss-only promotion is prohibited")
        if self.self_promotion and self.decision == "promote":
            raise IRCheckpointPromotionError("self-promotion is prohibited")
        if self.decision == "promote":
            if not self.admitted_gates:
                raise IRCheckpointPromotionError(
                    "promotion requires admitted non-loss gates"
                )
            if self.admitted_gates == ("lineage",) or set(self.admitted_gates) <= {"lineage"}:
                raise IRCheckpointPromotionError(
                    "promotion requires lineage plus at least one quality gate"
                )
            required = {"lineage", "semantic", "proof"}
            missing = sorted(required - set(self.admitted_gates))
            if missing:
                raise IRCheckpointPromotionError(
                    "promotion missing required gates: " + ", ".join(missing)
                )

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.to_dict(),
            domain="ir-promotion-manifest",
            schema_version=self.schema_version,
        )

    @property
    def digest(self) -> str:
        return self.identity.digest

    @property
    def cid(self) -> str:
        return self.identity.cid

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted_gates": list(self.admitted_gates),
            "actor_identity": self.actor_identity,
            "baseline_checkpoint_id": self.baseline_checkpoint_id,
            "candidate_checkpoint_id": self.candidate_checkpoint_id,
            "decision": self.decision,
            "evaluation_report_identity": self.evaluation_report_identity,
            "expected_current_pointer": self.expected_current_pointer,
            "human_approval_identity": self.human_approval_identity,
            "loss_only": self.loss_only,
            "policy_identity": self.policy_identity,
            "promotion_id": self.promotion_id,
            "proof_evidence_identity": self.proof_evidence_identity,
            "reason": self.reason,
            "schema_version": self.schema_version,
            "self_promotion": self.self_promotion,
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
    def from_dict(cls, value: Mapping[str, Any]) -> "IRPromotionManifest":
        value = _mapping(value, "IR promotion manifest")
        schema = str(value.get("schema_version") or "")
        if schema in {CHECKPOINT_MANIFEST_SCHEMA_VERSION, IR_CHECKPOINT_MANIFEST_SCHEMA}:
            raise IRCheckpointValidationError(
                "incompatible manifest aliasing: checkpoint manifests cannot "
                "be treated as IRPromotionManifest@1"
            )
        _reject_unknown(
            value,
            frozenset(
                {
                    "admitted_gates",
                    "actor_identity",
                    "baseline_checkpoint_id",
                    "candidate_checkpoint_id",
                    "decision",
                    "evaluation_report_identity",
                    "expected_current_pointer",
                    "human_approval_identity",
                    "loss_only",
                    "policy_identity",
                    "promotion_id",
                    "proof_evidence_identity",
                    "reason",
                    "schema_version",
                    "self_promotion",
                }
            ),
            "IR promotion manifest",
        )
        return cls(
            promotion_id=value.get("promotion_id", ""),
            candidate_checkpoint_id=value.get("candidate_checkpoint_id", ""),
            baseline_checkpoint_id=value.get("baseline_checkpoint_id", ""),
            expected_current_pointer=value.get("expected_current_pointer", ""),
            actor_identity=value.get("actor_identity", ""),
            policy_identity=value.get("policy_identity", ""),
            evaluation_report_identity=value.get("evaluation_report_identity", ""),
            proof_evidence_identity=value.get("proof_evidence_identity", ""),
            admitted_gates=value.get("admitted_gates", ()),
            decision=value.get("decision", ""),
            reason=value.get("reason", ""),
            human_approval_identity=value.get("human_approval_identity", ""),
            loss_only=value.get("loss_only", False),
            self_promotion=value.get("self_promotion", False),
            schema_version=value.get("schema_version", IR_PROMOTION_MANIFEST_SCHEMA),
        )

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> "IRPromotionManifest":
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, UnicodeDecodeError) as exc:
            raise IRCheckpointValidationError(
                "IR promotion manifest must be valid JSON"
            ) from exc
        return cls.from_dict(_mapping(decoded, "IR promotion manifest"))


def validate_ir_promotion_manifest(
    value: IRPromotionManifest | Mapping[str, Any],
) -> IRPromotionManifest:
    """Return a defensively reconstructed promotion manifest."""

    if isinstance(value, IRPromotionManifest):
        return IRPromotionManifest.from_dict(value.to_dict())
    return IRPromotionManifest.from_dict(value)


@dataclass(frozen=True, slots=True)
class IRCheckpointPointer:
    """Exactly-one current pointer.  Absence is represented by omitting it."""

    checkpoint_id: str
    artifact_digest: str
    record_digest: str
    fence: int = 0
    schema_version: str = IR_CHECKPOINT_POINTER_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != IR_CHECKPOINT_POINTER_SCHEMA:
            raise IRCheckpointValidationError(
                f"unsupported checkpoint pointer schema: {self.schema_version!r}"
            )
        object.__setattr__(
            self,
            "checkpoint_id",
            _namespaced_id(
                self.checkpoint_id,
                prefix=IR_CHECKPOINT_ID_PREFIX,
                field_name="checkpoint_id",
            ),
        )
        object.__setattr__(
            self, "artifact_digest", _digest(self.artifact_digest, "artifact_digest")
        )
        object.__setattr__(
            self, "record_digest", _digest(self.record_digest, "record_digest")
        )
        object.__setattr__(self, "fence", _non_negative_int(self.fence, "fence"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_digest": self.artifact_digest,
            "checkpoint_id": self.checkpoint_id,
            "fence": self.fence,
            "record_digest": self.record_digest,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "IRCheckpointPointer":
        value = _mapping(value, "IR checkpoint pointer")
        _reject_unknown(
            value,
            frozenset(
                {
                    "artifact_digest",
                    "checkpoint_id",
                    "fence",
                    "record_digest",
                    "schema_version",
                }
            ),
            "IR checkpoint pointer",
        )
        return cls(
            checkpoint_id=value.get("checkpoint_id", ""),
            artifact_digest=value.get("artifact_digest", ""),
            record_digest=value.get("record_digest", ""),
            fence=value.get("fence", 0),
            schema_version=value.get("schema_version", IR_CHECKPOINT_POINTER_SCHEMA),
        )

    @classmethod
    def from_manifest(cls, manifest: IRCheckpointManifest, *, fence: int) -> "IRCheckpointPointer":
        return cls(
            checkpoint_id=manifest.checkpoint_id,
            artifact_digest=manifest.digest,
            record_digest=manifest.record_digest,
            fence=fence,
        )


__all__ = [
    "CHECKPOINT_MANIFEST_SCHEMA_VERSION",
    "FORMALIZATION_ADVISOR_LEGACY_KIND",
    "IR_CHECKPOINT_ARTIFACT_IDENTITY_KEYS",
    "IR_CHECKPOINT_ID_PREFIX",
    "IR_CHECKPOINT_LIFECYCLE_SCHEMA",
    "IR_CHECKPOINT_LIFECYCLE_STATES",
    "IR_CHECKPOINT_LIFECYCLE_TRANSITIONS",
    "IR_CHECKPOINT_M1_FIELDS",
    "IR_CHECKPOINT_M1_IDENTITY_FIELDS",
    "IR_CHECKPOINT_MANIFEST_SCHEMA",
    "IR_CHECKPOINT_POINTER_SCHEMA",
    "IR_CHECKPOINT_SIDE_OUTCOME_KINDS",
    "IR_CHECKPOINT_SIDE_OUTCOME_SCHEMA",
    "IR_CHECKPOINT_SOURCE_KINDS",
    "IR_CHECKPOINT_TERMINAL_STATES",
    "IR_PROMOTION_DECISIONS",
    "IR_PROMOTION_ID_PREFIX",
    "IR_PROMOTION_MANIFEST_SCHEMA",
    "IR_PROMOTION_REQUIRED_GATES",
    "MODAL_STATE_LEGACY_KIND",
    "CheckpointManifest",
    "IRCheckpointLifecycleError",
    "IRCheckpointManifest",
    "IRCheckpointPointer",
    "IRCheckpointPromotionError",
    "IRCheckpointSideOutcome",
    "IRCheckpointValidationError",
    "IRPromotionManifest",
    "adapt_formalization_advisor_manifest",
    "allowed_lifecycle_transition",
    "complete_artifact_identities",
    "validate_checkpoint_manifest",
    "validate_ir_checkpoint_manifest",
    "validate_ir_promotion_manifest",
    "verify_ir_checkpoint_manifest",
    "verify_lifecycle_transition",
]
