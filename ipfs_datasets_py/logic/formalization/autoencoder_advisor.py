"""Domain-neutral autoencoder formalization advisor.

Generalizes modal-autoencoder introspection, ranking, compression, and
repair guidance beyond legal-only samples.  The advisor consumes shared
:class:`~.samples.FormalizationSample` / feature / artifact contracts and
software-verification logic families.  It reuses the bounded
:class:`~.advisor.BoundedFormalizationAdvisor` for candidate repairs without
editing the Legal modal training pipeline.

Authority boundaries (fail closed):

* ranking and compression are advisory only — never applicability or truth;
* repairs cannot alter sources, assumptions, modalities, trust, license, or
  review fields (enforced by the generic advisor);
* checkpoints bind schema, code, and data digests;
* outputs always carry ``authority="unverified_candidate_only"``;
* train/eval splits reject duplicate and source-family leakage.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, Protocol, runtime_checkable

from ipfs_datasets_py.logic.ir_core.claims import FrozenMap, thaw_json
from ipfs_datasets_py.logic.ir_core.identity import (
    CanonicalIdentity,
    canonical_identity,
)

from .advisor import (
    AdvisorConfig,
    AdvisorModel,
    AdvisorResult,
    AdvisorValidationError,
    BoundedFormalizationAdvisor,
    FormalizationAdvisorRequest,
    RepairScope,
)
from .checkpoints import CheckpointManifest, validate_checkpoint_manifest
from .compiler import FormalizationArtifact
from .features import FormalizationFeatures, validate_source_free_features
from .samples import (
    FormalizationSample,
    _DIGEST_RE,
    _identifier,
    _mapping,
    _reject_unknown,
    _sequence,
    _text,
    _unique_identifiers,
)
from .views import FormalFormula, FormalizationView, ViewRegistry


AUTOENCODER_ADVISOR_CONFIG_SCHEMA_VERSION: Final = (
    "formalization-autoencoder-advisor-config/v1"
)
AUTOENCODER_CHECKPOINT_BINDING_SCHEMA_VERSION: Final = (
    "formalization-autoencoder-checkpoint-binding/v1"
)
RANKED_VIEW_SCHEMA_VERSION: Final = "formalization-ranked-view/v1"
RANKED_PREMISE_SCHEMA_VERSION: Final = "formalization-ranked-premise/v1"
COMPRESSION_PLAN_SCHEMA_VERSION: Final = "formalization-compression-plan/v1"
INTROSPECTION_SCHEMA_VERSION: Final = "formalization-autoencoder-introspection/v1"
AUTOENCODER_ADVICE_SCHEMA_VERSION: Final = "formalization-autoencoder-advice/v1"
SPLIT_EXAMPLE_SCHEMA_VERSION: Final = "formalization-split-example/v1"
SPLIT_MANIFEST_SCHEMA_VERSION: Final = "formalization-split-manifest/v1"
FEATURE_CONTRIBUTION_SCHEMA_VERSION: Final = (
    "formalization-autoencoder-feature-contribution/v1"
)

FORMALIZATION_AUTOENCODER_ADVISOR_ID: Final = "formalization:autoencoder-advisor"
FORMALIZATION_AUTOENCODER_ADVISOR_VERSION: Final = (
    "formalization-autoencoder-advisor/v1"
)
UNVERIFIED_AUTHORITY: Final = "unverified_candidate_only"

_PARTITIONS: Final = frozenset({"train", "validation", "test", "held_out"})
_MAX_RANKED_ITEMS: Final = 256
_MAX_FEATURES_IN_PLAN: Final = 4_096
_SCORE_EPS: Final = 1e-12

_AUTHORITY_CLAIM_KEYS: Final = frozenset(
    {
        "authorization_status",
        "execution_result",
        "execution_status",
        "is_valid",
        "proof_result",
        "proof_status",
        "solver_result",
        "verification_result",
        "verification_status",
    }
)


class AutoencoderAdvisorValidationError(AdvisorValidationError):
    """Raised when autoencoder advisor inputs or outputs are unsafe."""


class SplitLeakageError(AutoencoderAdvisorValidationError):
    """Raised when a split crosses duplicate or source-family boundaries."""


class RankingKind(str, Enum):
    """What an advisory ranking targets."""

    VIEW = "view"
    PREMISE = "premise"
    FORMULA = "formula"


class PartitionName(str, Enum):
    """Canonical evaluation partitions for formalization corpora."""

    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"
    HELD_OUT = "held_out"


def _positive_int(value: Any, field_name: str, *, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise AutoencoderAdvisorValidationError(
            f"{field_name} must be a positive integer"
        )
    if value > maximum:
        raise AutoencoderAdvisorValidationError(
            f"{field_name} must not exceed the hard limit {maximum}"
        )
    return value


def _non_negative_int(value: Any, field_name: str, *, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AutoencoderAdvisorValidationError(
            f"{field_name} must be a non-negative integer"
        )
    if value > maximum:
        raise AutoencoderAdvisorValidationError(
            f"{field_name} must not exceed the hard limit {maximum}"
        )
    return value


def _digest(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise AutoencoderAdvisorValidationError(
            f"{field_name} must be a lowercase sha256:<hex> digest"
        )
    return value


def _finite_score(value: Any, field_name: str = "score") -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AutoencoderAdvisorValidationError(f"{field_name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise AutoencoderAdvisorValidationError(f"{field_name} must be finite")
    return result


def _unit_interval(value: Any, field_name: str) -> float:
    result = _finite_score(value, field_name)
    if result < 0.0 or result > 1.0:
        raise AutoencoderAdvisorValidationError(
            f"{field_name} must be between zero and one"
        )
    return result


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _content_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()


def _reject_authority_payload(value: Any, *, path: str = "") -> None:
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = re.sub(r"[^a-z0-9]+", "_", str(raw_key).lower()).strip("_")
            child_path = f"{path}/{raw_key}"
            if key in _AUTHORITY_CLAIM_KEYS:
                raise AutoencoderAdvisorValidationError(
                    f"autoencoder output cannot claim proof or execution "
                    f"authority at {child_path}"
                )
            if key in {"status", "verdict"} and isinstance(child, str):
                if re.sub(r"[^a-z0-9]+", "_", child.lower()).strip("_") in {
                    "authorized",
                    "executed",
                    "proved",
                    "verified",
                    "valid",
                }:
                    raise AutoencoderAdvisorValidationError(
                        "autoencoder output cannot claim proof or execution "
                        f"authority at {child_path}"
                    )
            _reject_authority_payload(child, path=child_path)
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for index, child in enumerate(value):
            _reject_authority_payload(child, path=f"{path}/{index}")


def _softmax(scores: Mapping[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    peak = max(scores.values())
    exps = {
        key: math.exp(float(value) - peak) for key, value in scores.items()
    }
    total = sum(exps.values())
    if total <= _SCORE_EPS:
        equal = 1.0 / len(scores)
        return {key: equal for key in scores}
    return {key: value / total for key, value in exps.items()}


@dataclass(frozen=True, slots=True)
class AutoencoderAdvisorConfig:
    """Immutable bounds for ranking, compression, and repair assistance."""

    advisor_id: str = FORMALIZATION_AUTOENCODER_ADVISOR_ID
    advisor_version: str = FORMALIZATION_AUTOENCODER_ADVISOR_VERSION
    config_id: str = "default"
    max_ranked_views: int = 16
    max_ranked_premises: int = 32
    max_compression_features: int = 64
    max_candidates: int = 4
    max_formulas_per_candidate: int = 8
    max_expression_nodes: int = 512
    max_expression_depth: int = 32
    max_expression_bytes: int = 16_384
    protected_field_names: tuple[str, ...] = ()
    schema_version: str = AUTOENCODER_ADVISOR_CONFIG_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "advisor_id", _identifier(self.advisor_id, "advisor_id")
        )
        object.__setattr__(
            self,
            "advisor_version",
            _identifier(self.advisor_version, "advisor_version"),
        )
        object.__setattr__(
            self, "config_id", _identifier(self.config_id, "config_id")
        )
        for name, maximum in (
            ("max_ranked_views", _MAX_RANKED_ITEMS),
            ("max_ranked_premises", _MAX_RANKED_ITEMS),
            ("max_compression_features", _MAX_FEATURES_IN_PLAN),
            ("max_candidates", 64),
            ("max_formulas_per_candidate", 256),
            ("max_expression_nodes", 65_536),
            ("max_expression_depth", 128),
            ("max_expression_bytes", 1_048_576),
        ):
            object.__setattr__(
                self,
                name,
                _positive_int(getattr(self, name), name, maximum=maximum),
            )
        extras = tuple(
            _identifier(item, "protected_field_names")
            for item in self.protected_field_names
        )
        object.__setattr__(self, "protected_field_names", tuple(sorted(set(extras))))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != AUTOENCODER_ADVISOR_CONFIG_SCHEMA_VERSION:
            raise AutoencoderAdvisorValidationError(
                f"unsupported autoencoder advisor config schema: "
                f"{self.schema_version!r}"
            )

    def to_advisor_config(self) -> AdvisorConfig:
        """Project hard bounds onto the generic bounded-advisor config."""

        return AdvisorConfig(
            advisor_id=self.advisor_id,
            advisor_version=self.advisor_version,
            config_id=self.config_id,
            max_candidates=self.max_candidates,
            max_formulas_per_candidate=self.max_formulas_per_candidate,
            max_expression_nodes=self.max_expression_nodes,
            max_expression_depth=self.max_expression_depth,
            max_expression_bytes=self.max_expression_bytes,
            protected_field_names=self.protected_field_names,
        )

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.to_dict(),
            domain="formalization-autoencoder-advisor-config",
            schema_version=self.schema_version,
            collection_semantics={"/protected_field_names": "set-like"},
        )

    @property
    def digest(self) -> str:
        return self.identity.digest

    def to_dict(self) -> dict[str, Any]:
        return {
            "advisor_id": self.advisor_id,
            "advisor_version": self.advisor_version,
            "config_id": self.config_id,
            "max_candidates": self.max_candidates,
            "max_compression_features": self.max_compression_features,
            "max_expression_bytes": self.max_expression_bytes,
            "max_expression_depth": self.max_expression_depth,
            "max_expression_nodes": self.max_expression_nodes,
            "max_formulas_per_candidate": self.max_formulas_per_candidate,
            "max_ranked_premises": self.max_ranked_premises,
            "max_ranked_views": self.max_ranked_views,
            "protected_field_names": list(self.protected_field_names),
            "schema_version": self.schema_version,
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AutoencoderAdvisorConfig":
        value = _mapping(value, "autoencoder advisor config")
        _reject_unknown(
            value,
            frozenset(
                {
                    "advisor_id",
                    "advisor_version",
                    "config_id",
                    "max_candidates",
                    "max_compression_features",
                    "max_expression_bytes",
                    "max_expression_depth",
                    "max_expression_nodes",
                    "max_formulas_per_candidate",
                    "max_ranked_premises",
                    "max_ranked_views",
                    "protected_field_names",
                    "schema_version",
                }
            ),
            "autoencoder advisor config",
        )
        return cls(
            advisor_id=value.get(
                "advisor_id", FORMALIZATION_AUTOENCODER_ADVISOR_ID
            ),
            advisor_version=value.get(
                "advisor_version", FORMALIZATION_AUTOENCODER_ADVISOR_VERSION
            ),
            config_id=value.get("config_id", "default"),
            max_ranked_views=value.get("max_ranked_views", 16),
            max_ranked_premises=value.get("max_ranked_premises", 32),
            max_compression_features=value.get("max_compression_features", 64),
            max_candidates=value.get("max_candidates", 4),
            max_formulas_per_candidate=value.get(
                "max_formulas_per_candidate", 8
            ),
            max_expression_nodes=value.get("max_expression_nodes", 512),
            max_expression_depth=value.get("max_expression_depth", 32),
            max_expression_bytes=value.get("max_expression_bytes", 16_384),
            protected_field_names=tuple(
                _sequence(
                    value.get("protected_field_names", ()),
                    "protected_field_names",
                )
            ),
            schema_version=value.get(
                "schema_version", AUTOENCODER_ADVISOR_CONFIG_SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_json(
        cls, value: str | bytes | bytearray
    ) -> "AutoencoderAdvisorConfig":
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, UnicodeDecodeError) as exc:
            raise AutoencoderAdvisorValidationError(
                "autoencoder advisor config must be valid JSON"
            ) from exc
        return cls.from_dict(_mapping(decoded, "autoencoder advisor config"))


@dataclass(frozen=True, slots=True)
class AutoencoderCheckpointBinding:
    """Binds schemas, code, and data digests to a checkpoint head.

    The domain-separated :class:`CheckpointManifest` already records ontology
    and view-registry identity.  This binding additionally pins the feature
    schema, advisor config, source-code fingerprint, and training-data
    snapshot so transfer across software-verification families stays
    auditable.
    """

    checkpoint: CheckpointManifest
    feature_schema_version: str
    advisor_config_identity: str
    code_fingerprint: str
    data_snapshot_identity: str
    schema_version: str = AUTOENCODER_CHECKPOINT_BINDING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "checkpoint", validate_checkpoint_manifest(self.checkpoint)
        )
        object.__setattr__(
            self,
            "feature_schema_version",
            _identifier(
                self.feature_schema_version, "feature_schema_version"
            ),
        )
        object.__setattr__(
            self,
            "advisor_config_identity",
            _digest(self.advisor_config_identity, "advisor_config_identity"),
        )
        object.__setattr__(
            self,
            "code_fingerprint",
            _digest(self.code_fingerprint, "code_fingerprint"),
        )
        object.__setattr__(
            self,
            "data_snapshot_identity",
            _digest(self.data_snapshot_identity, "data_snapshot_identity"),
        )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != AUTOENCODER_CHECKPOINT_BINDING_SCHEMA_VERSION:
            raise AutoencoderAdvisorValidationError(
                f"unsupported checkpoint binding schema: {self.schema_version!r}"
            )
        if self.checkpoint.feature_schema_version != self.feature_schema_version:
            raise AutoencoderAdvisorValidationError(
                "checkpoint feature schema does not match binding"
            )

    def require_compatible(
        self,
        *,
        domain: str,
        ontology_identity: str,
        view_registry_identity: str,
        feature_schema_version: str,
        advisor_config_identity: str,
        code_fingerprint: str,
        data_snapshot_identity: str,
    ) -> "AutoencoderCheckpointBinding":
        """Fail closed unless every schema/code/data binding matches."""

        self.checkpoint.require_compatible(
            domain=domain,
            ontology_identity=ontology_identity,
            view_registry_identity=view_registry_identity,
            feature_schema_version=feature_schema_version,
        )
        expected = {
            "feature_schema_version": _identifier(
                feature_schema_version, "feature_schema_version"
            ),
            "advisor_config_identity": _digest(
                advisor_config_identity, "advisor_config_identity"
            ),
            "code_fingerprint": _digest(code_fingerprint, "code_fingerprint"),
            "data_snapshot_identity": _digest(
                data_snapshot_identity, "data_snapshot_identity"
            ),
        }
        mismatches = [
            name
            for name, wanted in expected.items()
            if getattr(self, name) != wanted
        ]
        if mismatches:
            raise AutoencoderAdvisorValidationError(
                "autoencoder checkpoint binding is incompatible with "
                + ", ".join(sorted(mismatches))
            )
        return self

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.to_dict(),
            domain=f"formalization-autoencoder-checkpoint:{self.checkpoint.domain}",
            schema_version=self.schema_version,
        )

    @property
    def digest(self) -> str:
        return self.identity.digest

    def to_dict(self) -> dict[str, Any]:
        return {
            "advisor_config_identity": self.advisor_config_identity,
            "checkpoint": self.checkpoint.to_dict(),
            "code_fingerprint": self.code_fingerprint,
            "data_snapshot_identity": self.data_snapshot_identity,
            "feature_schema_version": self.feature_schema_version,
            "schema_version": self.schema_version,
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AutoencoderCheckpointBinding":
        value = _mapping(value, "autoencoder checkpoint binding")
        _reject_unknown(
            value,
            frozenset(
                {
                    "advisor_config_identity",
                    "checkpoint",
                    "code_fingerprint",
                    "data_snapshot_identity",
                    "feature_schema_version",
                    "schema_version",
                }
            ),
            "autoencoder checkpoint binding",
        )
        return cls(
            checkpoint=CheckpointManifest.from_dict(
                _mapping(value.get("checkpoint", {}), "checkpoint")
            ),
            feature_schema_version=value.get("feature_schema_version", ""),
            advisor_config_identity=value.get("advisor_config_identity", ""),
            code_fingerprint=value.get("code_fingerprint", ""),
            data_snapshot_identity=value.get("data_snapshot_identity", ""),
            schema_version=value.get(
                "schema_version", AUTOENCODER_CHECKPOINT_BINDING_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class FeatureContribution:
    """One advisory contribution of a feature or view signal."""

    name: str
    score: float
    kind: str = "feature"
    schema_version: str = FEATURE_CONTRIBUTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _identifier(self.name, "name"))
        object.__setattr__(self, "score", _finite_score(self.score))
        object.__setattr__(self, "kind", _identifier(self.kind, "kind"))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != FEATURE_CONTRIBUTION_SCHEMA_VERSION:
            raise AutoencoderAdvisorValidationError(
                f"unsupported feature contribution schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "schema_version": self.schema_version,
            "score": self.score,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FeatureContribution":
        value = _mapping(value, "feature contribution")
        _reject_unknown(
            value,
            frozenset({"kind", "name", "schema_version", "score"}),
            "feature contribution",
        )
        return cls(
            name=value.get("name", ""),
            score=value.get("score", 0.0),
            kind=value.get("kind", "feature"),
            schema_version=value.get(
                "schema_version", FEATURE_CONTRIBUTION_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class RankedView:
    """Advisory ranking of one formalization view for a sample."""

    view_id: str
    logic_family: str
    rank: int
    score: float
    reason: str = ""
    schema_version: str = RANKED_VIEW_SCHEMA_VERSION
    authority: str = UNVERIFIED_AUTHORITY

    def __post_init__(self) -> None:
        object.__setattr__(self, "view_id", _identifier(self.view_id, "view_id"))
        object.__setattr__(
            self, "logic_family", _identifier(self.logic_family, "logic_family")
        )
        object.__setattr__(
            self, "rank", _non_negative_int(self.rank, "rank", maximum=_MAX_RANKED_ITEMS)
        )
        object.__setattr__(self, "score", _finite_score(self.score))
        if not isinstance(self.reason, str):
            raise AutoencoderAdvisorValidationError("reason must be a string")
        if len(self.reason) > 1_024:
            raise AutoencoderAdvisorValidationError("reason exceeds 1024 characters")
        if self.authority != UNVERIFIED_AUTHORITY:
            raise AutoencoderAdvisorValidationError(
                "ranked views are candidate-only and cannot claim authority"
            )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != RANKED_VIEW_SCHEMA_VERSION:
            raise AutoencoderAdvisorValidationError(
                f"unsupported ranked view schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "logic_family": self.logic_family,
            "rank": self.rank,
            "reason": self.reason,
            "schema_version": self.schema_version,
            "score": self.score,
            "view_id": self.view_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RankedView":
        value = _mapping(value, "ranked view")
        _reject_unknown(
            value,
            frozenset(
                {
                    "authority",
                    "logic_family",
                    "rank",
                    "reason",
                    "schema_version",
                    "score",
                    "view_id",
                }
            ),
            "ranked view",
        )
        return cls(
            view_id=value.get("view_id", ""),
            logic_family=value.get("logic_family", ""),
            rank=value.get("rank", 0),
            score=value.get("score", 0.0),
            reason=value.get("reason", ""),
            schema_version=value.get("schema_version", RANKED_VIEW_SCHEMA_VERSION),
            authority=value.get("authority", UNVERIFIED_AUTHORITY),
        )


@dataclass(frozen=True, slots=True)
class RankedPremise:
    """Advisory ranking of one source-grounded premise candidate.

    Ranking never elevates a premise into applicability or truth.  Empty
    source grounding is rejected so ungrounded model inventions cannot enter
    the ranked set.
    """

    premise_id: str
    statement: str
    source_ref_ids: tuple[str, ...]
    logic_family: str
    rank: int
    score: float
    formula_id: str = ""
    reason: str = ""
    schema_version: str = RANKED_PREMISE_SCHEMA_VERSION
    authority: str = UNVERIFIED_AUTHORITY

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "premise_id", _identifier(self.premise_id, "premise_id")
        )
        statement = _text(self.statement, "statement")
        if len(statement) > 4_096:
            raise AutoencoderAdvisorValidationError(
                "premise statement exceeds 4096 characters"
            )
        object.__setattr__(self, "statement", statement)
        object.__setattr__(
            self,
            "source_ref_ids",
            _unique_identifiers(self.source_ref_ids, "source_ref_ids"),
        )
        if not self.source_ref_ids:
            raise AutoencoderAdvisorValidationError(
                f"premise {self.premise_id!r} is ungrounded: "
                "source_ref_ids must be non-empty"
            )
        object.__setattr__(
            self, "logic_family", _identifier(self.logic_family, "logic_family")
        )
        object.__setattr__(
            self, "rank", _non_negative_int(self.rank, "rank", maximum=_MAX_RANKED_ITEMS)
        )
        object.__setattr__(self, "score", _finite_score(self.score))
        if self.formula_id:
            object.__setattr__(
                self, "formula_id", _identifier(self.formula_id, "formula_id")
            )
        if not isinstance(self.reason, str) or len(self.reason) > 1_024:
            raise AutoencoderAdvisorValidationError(
                "reason must be a string of at most 1024 characters"
            )
        if self.authority != UNVERIFIED_AUTHORITY:
            raise AutoencoderAdvisorValidationError(
                "ranked premises are candidate-only and cannot claim authority"
            )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != RANKED_PREMISE_SCHEMA_VERSION:
            raise AutoencoderAdvisorValidationError(
                f"unsupported ranked premise schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "formula_id": self.formula_id,
            "logic_family": self.logic_family,
            "premise_id": self.premise_id,
            "rank": self.rank,
            "reason": self.reason,
            "schema_version": self.schema_version,
            "score": self.score,
            "source_ref_ids": list(self.source_ref_ids),
            "statement": self.statement,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RankedPremise":
        value = _mapping(value, "ranked premise")
        _reject_unknown(
            value,
            frozenset(
                {
                    "authority",
                    "formula_id",
                    "logic_family",
                    "premise_id",
                    "rank",
                    "reason",
                    "schema_version",
                    "score",
                    "source_ref_ids",
                    "statement",
                }
            ),
            "ranked premise",
        )
        return cls(
            premise_id=value.get("premise_id", ""),
            statement=value.get("statement", ""),
            source_ref_ids=tuple(
                _sequence(value.get("source_ref_ids", ()), "source_ref_ids")
            ),
            logic_family=value.get("logic_family", "unspecified"),
            rank=value.get("rank", 0),
            score=value.get("score", 0.0),
            formula_id=value.get("formula_id", ""),
            reason=value.get("reason", ""),
            schema_version=value.get(
                "schema_version", RANKED_PREMISE_SCHEMA_VERSION
            ),
            authority=value.get("authority", UNVERIFIED_AUTHORITY),
        )


@dataclass(frozen=True, slots=True)
class CompressionPlan:
    """Bounded feature/view compression guidance for one sample.

    Compression is advisory reconstruction guidance: it never mutates the
    underlying sample, artifact, or provenance.
    """

    sample_id: str
    retained_feature_names: tuple[str, ...]
    dropped_feature_names: tuple[str, ...]
    retained_view_ids: tuple[str, ...]
    estimated_compression_ratio: float
    reconstruction_score: float
    schema_version: str = COMPRESSION_PLAN_SCHEMA_VERSION
    authority: str = UNVERIFIED_AUTHORITY

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "sample_id", _identifier(self.sample_id, "sample_id")
        )
        retained = _unique_identifiers(
            self.retained_feature_names, "retained_feature_names", sort=True
        )
        dropped = _unique_identifiers(
            self.dropped_feature_names, "dropped_feature_names", sort=True
        )
        if set(retained) & set(dropped):
            raise AutoencoderAdvisorValidationError(
                "retained and dropped feature names must be disjoint"
            )
        object.__setattr__(self, "retained_feature_names", retained)
        object.__setattr__(self, "dropped_feature_names", dropped)
        object.__setattr__(
            self,
            "retained_view_ids",
            _unique_identifiers(
                self.retained_view_ids, "retained_view_ids", sort=True
            ),
        )
        object.__setattr__(
            self,
            "estimated_compression_ratio",
            _finite_score(
                self.estimated_compression_ratio, "estimated_compression_ratio"
            ),
        )
        if self.estimated_compression_ratio < 1.0:
            raise AutoencoderAdvisorValidationError(
                "estimated_compression_ratio must be at least 1.0"
            )
        object.__setattr__(
            self,
            "reconstruction_score",
            _unit_interval(self.reconstruction_score, "reconstruction_score"),
        )
        if self.authority != UNVERIFIED_AUTHORITY:
            raise AutoencoderAdvisorValidationError(
                "compression plans are candidate-only and cannot claim authority"
            )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != COMPRESSION_PLAN_SCHEMA_VERSION:
            raise AutoencoderAdvisorValidationError(
                f"unsupported compression plan schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "dropped_feature_names": list(self.dropped_feature_names),
            "estimated_compression_ratio": self.estimated_compression_ratio,
            "reconstruction_score": self.reconstruction_score,
            "retained_feature_names": list(self.retained_feature_names),
            "retained_view_ids": list(self.retained_view_ids),
            "sample_id": self.sample_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CompressionPlan":
        value = _mapping(value, "compression plan")
        _reject_unknown(
            value,
            frozenset(
                {
                    "authority",
                    "dropped_feature_names",
                    "estimated_compression_ratio",
                    "reconstruction_score",
                    "retained_feature_names",
                    "retained_view_ids",
                    "sample_id",
                    "schema_version",
                }
            ),
            "compression plan",
        )
        return cls(
            sample_id=value.get("sample_id", ""),
            retained_feature_names=tuple(
                _sequence(
                    value.get("retained_feature_names", ()),
                    "retained_feature_names",
                )
            ),
            dropped_feature_names=tuple(
                _sequence(
                    value.get("dropped_feature_names", ()),
                    "dropped_feature_names",
                )
            ),
            retained_view_ids=tuple(
                _sequence(value.get("retained_view_ids", ()), "retained_view_ids")
            ),
            estimated_compression_ratio=value.get(
                "estimated_compression_ratio", 1.0
            ),
            reconstruction_score=value.get("reconstruction_score", 1.0),
            schema_version=value.get(
                "schema_version", COMPRESSION_PLAN_SCHEMA_VERSION
            ),
            authority=value.get("authority", UNVERIFIED_AUTHORITY),
        )


@dataclass(frozen=True, slots=True)
class FormalizationIntrospection:
    """Domain-neutral introspection of ranking and reconstruction signals.

    This is the portable counterpart of legal-only
    ``AutoencoderIntrospection``: view distributions, reconstruction quality,
    and top contributions, without Legal IR training targets.
    """

    sample_id: str
    domain: str
    predicted_logic_family: str
    target_logic_family: str
    family_margin: float
    reconstruction_score: float
    view_distribution: FrozenMap
    predicted_view_distribution: FrozenMap
    top_feature_contributions: tuple[FeatureContribution, ...]
    synthesis_focus: tuple[str, ...] = ()
    schema_version: str = INTROSPECTION_SCHEMA_VERSION
    authority: str = UNVERIFIED_AUTHORITY

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "sample_id", _identifier(self.sample_id, "sample_id")
        )
        object.__setattr__(self, "domain", _identifier(self.domain, "domain"))
        object.__setattr__(
            self,
            "predicted_logic_family",
            _identifier(self.predicted_logic_family, "predicted_logic_family"),
        )
        object.__setattr__(
            self,
            "target_logic_family",
            _identifier(self.target_logic_family, "target_logic_family"),
        )
        object.__setattr__(
            self, "family_margin", _finite_score(self.family_margin, "family_margin")
        )
        object.__setattr__(
            self,
            "reconstruction_score",
            _unit_interval(self.reconstruction_score, "reconstruction_score"),
        )
        object.__setattr__(
            self,
            "view_distribution",
            self.view_distribution
            if isinstance(self.view_distribution, FrozenMap)
            else FrozenMap(_mapping(self.view_distribution, "view_distribution")),
        )
        object.__setattr__(
            self,
            "predicted_view_distribution",
            self.predicted_view_distribution
            if isinstance(self.predicted_view_distribution, FrozenMap)
            else FrozenMap(
                _mapping(
                    self.predicted_view_distribution,
                    "predicted_view_distribution",
                )
            ),
        )
        for name in ("view_distribution", "predicted_view_distribution"):
            mapping = getattr(self, name).to_dict()
            for key, raw in mapping.items():
                _identifier(key, f"{name} key")
                _unit_interval(raw, f"{name}[{key}]")
        contributions = tuple(
            item
            if isinstance(item, FeatureContribution)
            else FeatureContribution.from_dict(
                _mapping(item, "feature contribution")
            )
            for item in self.top_feature_contributions
        )
        if len(contributions) > _MAX_RANKED_ITEMS:
            raise AutoencoderAdvisorValidationError(
                "top_feature_contributions exceeds hard bound"
            )
        object.__setattr__(
            self,
            "top_feature_contributions",
            tuple(
                sorted(
                    contributions,
                    key=lambda item: (-item.score, item.name),
                )
            ),
        )
        object.__setattr__(
            self,
            "synthesis_focus",
            _unique_identifiers(self.synthesis_focus, "synthesis_focus", sort=True),
        )
        if self.authority != UNVERIFIED_AUTHORITY:
            raise AutoencoderAdvisorValidationError(
                "introspection is candidate-only and cannot claim authority"
            )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != INTROSPECTION_SCHEMA_VERSION:
            raise AutoencoderAdvisorValidationError(
                f"unsupported introspection schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "domain": self.domain,
            "family_margin": self.family_margin,
            "predicted_logic_family": self.predicted_logic_family,
            "predicted_view_distribution": self.predicted_view_distribution.to_dict(),
            "reconstruction_score": self.reconstruction_score,
            "sample_id": self.sample_id,
            "schema_version": self.schema_version,
            "synthesis_focus": list(self.synthesis_focus),
            "target_logic_family": self.target_logic_family,
            "top_feature_contributions": [
                item.to_dict() for item in self.top_feature_contributions
            ],
            "view_distribution": self.view_distribution.to_dict(),
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FormalizationIntrospection":
        value = _mapping(value, "formalization introspection")
        _reject_unknown(
            value,
            frozenset(
                {
                    "authority",
                    "domain",
                    "family_margin",
                    "predicted_logic_family",
                    "predicted_view_distribution",
                    "reconstruction_score",
                    "sample_id",
                    "schema_version",
                    "synthesis_focus",
                    "target_logic_family",
                    "top_feature_contributions",
                    "view_distribution",
                }
            ),
            "formalization introspection",
        )
        return cls(
            sample_id=value.get("sample_id", ""),
            domain=value.get("domain", ""),
            predicted_logic_family=value.get("predicted_logic_family", ""),
            target_logic_family=value.get("target_logic_family", ""),
            family_margin=value.get("family_margin", 0.0),
            reconstruction_score=value.get("reconstruction_score", 0.0),
            view_distribution=value.get("view_distribution", {}),
            predicted_view_distribution=value.get(
                "predicted_view_distribution", {}
            ),
            top_feature_contributions=tuple(
                FeatureContribution.from_dict(
                    _mapping(item, "feature contribution")
                )
                for item in _sequence(
                    value.get("top_feature_contributions", ()),
                    "top_feature_contributions",
                )
            ),
            synthesis_focus=tuple(
                _sequence(value.get("synthesis_focus", ()), "synthesis_focus")
            ),
            schema_version=value.get("schema_version", INTROSPECTION_SCHEMA_VERSION),
            authority=value.get("authority", UNVERIFIED_AUTHORITY),
        )

    @classmethod
    def from_json(
        cls, value: str | bytes | bytearray
    ) -> "FormalizationIntrospection":
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, UnicodeDecodeError) as exc:
            raise AutoencoderAdvisorValidationError(
                "formalization introspection must be valid JSON"
            ) from exc
        return cls.from_dict(_mapping(decoded, "formalization introspection"))


@dataclass(frozen=True, slots=True)
class FormalizationSplitExample:
    """One row in a leakage-safe formalization evaluation split."""

    sample_id: str
    domain: str
    partition: str
    source_family_id: str
    content_digest: str
    duplicate_family_id: str = ""
    generation_family_id: str = ""
    tags: tuple[str, ...] = ()
    schema_version: str = SPLIT_EXAMPLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "sample_id", _identifier(self.sample_id, "sample_id")
        )
        object.__setattr__(self, "domain", _identifier(self.domain, "domain"))
        partition = _identifier(self.partition, "partition")
        if partition not in _PARTITIONS:
            raise AutoencoderAdvisorValidationError(
                f"unknown split partition: {partition!r}"
            )
        object.__setattr__(self, "partition", partition)
        object.__setattr__(
            self,
            "source_family_id",
            _identifier(self.source_family_id, "source_family_id"),
        )
        object.__setattr__(
            self, "content_digest", _digest(self.content_digest, "content_digest")
        )
        if self.duplicate_family_id:
            object.__setattr__(
                self,
                "duplicate_family_id",
                _identifier(self.duplicate_family_id, "duplicate_family_id"),
            )
        if self.generation_family_id:
            object.__setattr__(
                self,
                "generation_family_id",
                _identifier(self.generation_family_id, "generation_family_id"),
            )
        object.__setattr__(
            self, "tags", _unique_identifiers(self.tags, "tags", sort=True)
        )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != SPLIT_EXAMPLE_SCHEMA_VERSION:
            raise AutoencoderAdvisorValidationError(
                f"unsupported split example schema: {self.schema_version!r}"
            )

    def family_keys(self) -> frozenset[str]:
        """Return all grouping keys used for leakage isolation."""

        keys = {
            f"source:{self.source_family_id}",
            f"content:{self.content_digest}",
        }
        if self.duplicate_family_id:
            keys.add(f"duplicate:{self.duplicate_family_id}")
        if self.generation_family_id:
            keys.add(f"generation:{self.generation_family_id}")
        return frozenset(keys)

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_digest": self.content_digest,
            "domain": self.domain,
            "duplicate_family_id": self.duplicate_family_id,
            "generation_family_id": self.generation_family_id,
            "partition": self.partition,
            "sample_id": self.sample_id,
            "schema_version": self.schema_version,
            "source_family_id": self.source_family_id,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FormalizationSplitExample":
        value = _mapping(value, "split example")
        _reject_unknown(
            value,
            frozenset(
                {
                    "content_digest",
                    "domain",
                    "duplicate_family_id",
                    "generation_family_id",
                    "partition",
                    "sample_id",
                    "schema_version",
                    "source_family_id",
                    "tags",
                }
            ),
            "split example",
        )
        return cls(
            sample_id=value.get("sample_id", ""),
            domain=value.get("domain", ""),
            partition=value.get("partition", ""),
            source_family_id=value.get("source_family_id", ""),
            content_digest=value.get("content_digest", ""),
            duplicate_family_id=value.get("duplicate_family_id", ""),
            generation_family_id=value.get("generation_family_id", ""),
            tags=tuple(_sequence(value.get("tags", ()), "tags")),
            schema_version=value.get(
                "schema_version", SPLIT_EXAMPLE_SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_sample(
        cls,
        sample: FormalizationSample,
        *,
        partition: str,
        source_family_id: str | None = None,
        duplicate_family_id: str = "",
        generation_family_id: str = "",
    ) -> "FormalizationSplitExample":
        """Build a split row from a domain-neutral formalization sample."""

        if not isinstance(sample, FormalizationSample):
            raise AutoencoderAdvisorValidationError(
                "sample must be a FormalizationSample"
            )
        sample.validate()
        family = source_family_id or (
            sorted(sample.source_ref_ids)[0]
            if sample.source_ref_ids
            else sample.declaration_id
        )
        return cls(
            sample_id=sample.sample_id,
            domain=sample.domain,
            partition=partition,
            source_family_id=family,
            content_digest=sample.declaration_digest,
            duplicate_family_id=duplicate_family_id,
            generation_family_id=generation_family_id,
            tags=sample.tags,
        )


@dataclass(frozen=True, slots=True)
class FormalizationSplitManifest:
    """Leakage-safe partition of formalization samples.

    Any source family, exact content digest, declared duplicate family, or
    generation family may appear in only one partition.
    """

    manifest_id: str
    domain: str
    examples: tuple[FormalizationSplitExample, ...]
    schema_version: str = SPLIT_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "manifest_id", _identifier(self.manifest_id, "manifest_id")
        )
        object.__setattr__(self, "domain", _identifier(self.domain, "domain"))
        examples = tuple(
            item
            if isinstance(item, FormalizationSplitExample)
            else FormalizationSplitExample.from_dict(
                _mapping(item, "split example")
            )
            for item in self.examples
        )
        if not examples:
            raise AutoencoderAdvisorValidationError(
                "split manifest requires at least one example"
            )
        sample_ids = [item.sample_id for item in examples]
        if len(sample_ids) != len(set(sample_ids)):
            raise AutoencoderAdvisorValidationError(
                "split example sample_ids must be unique"
            )
        foreign = [item.sample_id for item in examples if item.domain != self.domain]
        if foreign:
            raise AutoencoderAdvisorValidationError(
                "split examples must share the manifest domain: "
                + ", ".join(sorted(foreign)[:8])
            )
        object.__setattr__(
            self,
            "examples",
            tuple(sorted(examples, key=lambda item: item.sample_id)),
        )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != SPLIT_MANIFEST_SCHEMA_VERSION:
            raise AutoencoderAdvisorValidationError(
                f"unsupported split manifest schema: {self.schema_version!r}"
            )
        self.validate_no_leakage()

    def validate_no_leakage(self) -> "FormalizationSplitManifest":
        """Reject duplicate or source-family crossings across partitions."""

        key_partitions: dict[str, set[str]] = {}
        for example in self.examples:
            for key in example.family_keys():
                key_partitions.setdefault(key, set()).add(example.partition)
        leaks = sorted(
            key
            for key, partitions in key_partitions.items()
            if len(partitions) > 1
        )
        if leaks:
            raise SplitLeakageError(
                "split leaks source/duplicate families across partitions: "
                + ", ".join(leaks[:12])
            )
        return self

    def partition_samples(self, partition: str) -> tuple[str, ...]:
        partition = _identifier(partition, "partition")
        return tuple(
            item.sample_id
            for item in self.examples
            if item.partition == partition
        )

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.to_dict(),
            domain=f"formalization-split:{self.domain}",
            schema_version=self.schema_version,
            collection_semantics={
                "/examples": "set-like",
                "/examples/*/tags": "set-like",
            },
        )

    @property
    def digest(self) -> str:
        return self.identity.digest

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "examples": [item.to_dict() for item in self.examples],
            "manifest_id": self.manifest_id,
            "schema_version": self.schema_version,
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FormalizationSplitManifest":
        value = _mapping(value, "split manifest")
        _reject_unknown(
            value,
            frozenset(
                {"domain", "examples", "manifest_id", "schema_version"}
            ),
            "split manifest",
        )
        return cls(
            manifest_id=value.get("manifest_id", ""),
            domain=value.get("domain", ""),
            examples=tuple(
                FormalizationSplitExample.from_dict(
                    _mapping(item, "split example")
                )
                for item in _sequence(value.get("examples", ()), "examples")
            ),
            schema_version=value.get(
                "schema_version", SPLIT_MANIFEST_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class AutoencoderAdviceResult:
    """Complete autoencoder advisor output: ranking, compression, repairs.

    The optional ``repair_result`` is a generic :class:`AdvisorResult` and
    remains unverified candidate material.  Ranking and compression never
    establish truth or applicability.
    """

    sample_id: str
    domain: str
    ranked_views: tuple[RankedView, ...]
    ranked_premises: tuple[RankedPremise, ...]
    compression_plan: CompressionPlan
    introspection: FormalizationIntrospection
    config_identity: str
    checkpoint_binding_identity: str
    input_features_identity: str
    input_artifact_identity: str
    ontology_identity: str
    repair_result: AdvisorResult | None = None
    schema_version: str = AUTOENCODER_ADVICE_SCHEMA_VERSION
    authority: str = UNVERIFIED_AUTHORITY

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "sample_id", _identifier(self.sample_id, "sample_id")
        )
        object.__setattr__(self, "domain", _identifier(self.domain, "domain"))
        views = tuple(
            item
            if isinstance(item, RankedView)
            else RankedView.from_dict(_mapping(item, "ranked view"))
            for item in self.ranked_views
        )
        premises = tuple(
            item
            if isinstance(item, RankedPremise)
            else RankedPremise.from_dict(_mapping(item, "ranked premise"))
            for item in self.ranked_premises
        )
        view_ids = [item.view_id for item in views]
        if len(view_ids) != len(set(view_ids)):
            raise AutoencoderAdvisorValidationError(
                "ranked view IDs must be unique"
            )
        premise_ids = [item.premise_id for item in premises]
        if len(premise_ids) != len(set(premise_ids)):
            raise AutoencoderAdvisorValidationError(
                "ranked premise IDs must be unique"
            )
        object.__setattr__(
            self,
            "ranked_views",
            tuple(sorted(views, key=lambda item: (item.rank, item.view_id))),
        )
        object.__setattr__(
            self,
            "ranked_premises",
            tuple(
                sorted(premises, key=lambda item: (item.rank, item.premise_id))
            ),
        )
        if not isinstance(self.compression_plan, CompressionPlan):
            raise AutoencoderAdvisorValidationError(
                "compression_plan must be a CompressionPlan"
            )
        if not isinstance(self.introspection, FormalizationIntrospection):
            raise AutoencoderAdvisorValidationError(
                "introspection must be a FormalizationIntrospection"
            )
        if self.repair_result is not None and not isinstance(
            self.repair_result, AdvisorResult
        ):
            raise AutoencoderAdvisorValidationError(
                "repair_result must be an AdvisorResult or None"
            )
        for name in (
            "config_identity",
            "checkpoint_binding_identity",
            "input_features_identity",
            "input_artifact_identity",
            "ontology_identity",
        ):
            object.__setattr__(self, name, _digest(getattr(self, name), name))
        if self.authority != UNVERIFIED_AUTHORITY:
            raise AutoencoderAdvisorValidationError(
                "autoencoder advice cannot claim proof or execution authority"
            )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != AUTOENCODER_ADVICE_SCHEMA_VERSION:
            raise AutoencoderAdvisorValidationError(
                f"unsupported autoencoder advice schema: {self.schema_version!r}"
            )
        _reject_authority_payload(self.to_dict())

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.to_dict(),
            domain="formalization-autoencoder-advice",
            schema_version=self.schema_version,
            collection_semantics={
                "/ranked_premises": "ordered",
                "/ranked_views": "ordered",
            },
        )

    @property
    def digest(self) -> str:
        return self.identity.digest

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "checkpoint_binding_identity": self.checkpoint_binding_identity,
            "compression_plan": self.compression_plan.to_dict(),
            "config_identity": self.config_identity,
            "domain": self.domain,
            "input_artifact_identity": self.input_artifact_identity,
            "input_features_identity": self.input_features_identity,
            "introspection": self.introspection.to_dict(),
            "ontology_identity": self.ontology_identity,
            "ranked_premises": [item.to_dict() for item in self.ranked_premises],
            "ranked_views": [item.to_dict() for item in self.ranked_views],
            "repair_result": (
                self.repair_result.to_dict()
                if self.repair_result is not None
                else None
            ),
            "sample_id": self.sample_id,
            "schema_version": self.schema_version,
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AutoencoderAdviceResult":
        value = _mapping(value, "autoencoder advice")
        _reject_unknown(
            value,
            frozenset(
                {
                    "authority",
                    "checkpoint_binding_identity",
                    "compression_plan",
                    "config_identity",
                    "domain",
                    "input_artifact_identity",
                    "input_features_identity",
                    "introspection",
                    "ontology_identity",
                    "ranked_premises",
                    "ranked_views",
                    "repair_result",
                    "sample_id",
                    "schema_version",
                }
            ),
            "autoencoder advice",
        )
        repair = value.get("repair_result")
        return cls(
            sample_id=value.get("sample_id", ""),
            domain=value.get("domain", ""),
            ranked_views=tuple(
                RankedView.from_dict(_mapping(item, "ranked view"))
                for item in _sequence(value.get("ranked_views", ()), "ranked_views")
            ),
            ranked_premises=tuple(
                RankedPremise.from_dict(_mapping(item, "ranked premise"))
                for item in _sequence(
                    value.get("ranked_premises", ()), "ranked_premises"
                )
            ),
            compression_plan=CompressionPlan.from_dict(
                _mapping(value.get("compression_plan", {}), "compression plan")
            ),
            introspection=FormalizationIntrospection.from_dict(
                _mapping(value.get("introspection", {}), "introspection")
            ),
            config_identity=value.get("config_identity", ""),
            checkpoint_binding_identity=value.get(
                "checkpoint_binding_identity", ""
            ),
            input_features_identity=value.get("input_features_identity", ""),
            input_artifact_identity=value.get("input_artifact_identity", ""),
            ontology_identity=value.get("ontology_identity", ""),
            repair_result=(
                AdvisorResult.from_dict(_mapping(repair, "repair result"))
                if repair is not None
                else None
            ),
            schema_version=value.get(
                "schema_version", AUTOENCODER_ADVICE_SCHEMA_VERSION
            ),
            authority=value.get("authority", UNVERIFIED_AUTHORITY),
        )


@runtime_checkable
class AutoencoderScoringBackend(Protocol):
    """Optional untrusted scorer for views and premises.

    Implementations may wrap a trained modal autoencoder.  Outputs remain
    untrusted until the advisor re-validates and ranks them deterministically.
    """

    def score_views(
        self,
        *,
        features: FormalizationFeatures,
        view_ids: Sequence[str],
        logic_families: Mapping[str, str],
    ) -> Mapping[str, float]:
        """Return finite advisory scores keyed by view_id."""

    def score_premises(
        self,
        *,
        features: FormalizationFeatures,
        premise_ids: Sequence[str],
    ) -> Mapping[str, float]:
        """Return finite advisory scores keyed by premise_id."""


@dataclass(frozen=True, slots=True)
class FormalizationAutoencoderRequest:
    """Trusted input joining deterministic artifacts with checkpoint bindings."""

    artifact: FormalizationArtifact
    features: FormalizationFeatures
    checkpoint_binding: AutoencoderCheckpointBinding
    ontology_identity: str
    repair_scope: RepairScope | None = None
    target_logic_family: str = ""
    premise_candidates: tuple[RankedPremise, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.artifact, FormalizationArtifact):
            raise AutoencoderAdvisorValidationError(
                "artifact must be a FormalizationArtifact"
            )
        self.artifact.validate()
        object.__setattr__(
            self, "features", validate_source_free_features(self.features)
        )
        if not isinstance(self.checkpoint_binding, AutoencoderCheckpointBinding):
            raise AutoencoderAdvisorValidationError(
                "checkpoint_binding must be an AutoencoderCheckpointBinding"
            )
        object.__setattr__(
            self,
            "ontology_identity",
            _digest(self.ontology_identity, "ontology_identity"),
        )
        if self.repair_scope is not None and not isinstance(
            self.repair_scope, RepairScope
        ):
            raise AutoencoderAdvisorValidationError(
                "repair_scope must be a RepairScope or None"
            )
        if (
            self.features.sample_id != self.artifact.sample_id
            or self.features.domain != self.artifact.domain
            or self.features.declaration_digest
            != self.artifact.declaration_digest
        ):
            raise AutoencoderAdvisorValidationError(
                "features do not identify the input artifact declaration"
            )
        if self.target_logic_family:
            object.__setattr__(
                self,
                "target_logic_family",
                _identifier(self.target_logic_family, "target_logic_family"),
            )
        premises = tuple(
            item
            if isinstance(item, RankedPremise)
            else RankedPremise.from_dict(_mapping(item, "premise candidate"))
            for item in self.premise_candidates
        )
        object.__setattr__(self, "premise_candidates", premises)
        known_sources = {
            item.ref_id for item in self.artifact.source_map.sources
        }
        for premise in premises:
            unknown = set(premise.source_ref_ids) - known_sources
            if unknown:
                raise AutoencoderAdvisorValidationError(
                    f"premise {premise.premise_id!r} references unknown "
                    f"sources: {', '.join(sorted(unknown))}"
                )
        if self.repair_scope is not None:
            known_formula_ids = {
                item.formula_id for item in self.artifact.formulas
            }
            unknown_formulas = set(self.repair_scope.formula_ids) - known_formula_ids
            if unknown_formulas:
                raise AutoencoderAdvisorValidationError(
                    "repair scope references unknown formulas: "
                    + ", ".join(sorted(unknown_formulas))
                )


class FormalizationAutoencoderAdvisor:
    """Bounded domain-neutral autoencoder formalization advisor.

    Implements ``FormalizationAutoencoderAdvisor@1``:

    * ranks views and premises without elevating scores into truth;
    * proposes feature compression guidance;
    * optionally routes bounded repairs through
      :class:`BoundedFormalizationAdvisor`;
    * records checkpoint schema/code/data bindings on every result.
    """

    def __init__(
        self,
        config: AutoencoderAdvisorConfig | None = None,
        *,
        model: AdvisorModel | None = None,
        scoring_backend: AutoencoderScoringBackend | None = None,
        code_fingerprint: str | None = None,
        data_snapshot_identity: str | None = None,
    ) -> None:
        self.config = (
            config
            if isinstance(config, AutoencoderAdvisorConfig)
            else AutoencoderAdvisorConfig()
        )
        if model is not None:
            method = getattr(model, "generate_candidates", None)
            if not callable(method):
                raise TypeError("model must implement generate_candidates")
        self._model = model
        self._scoring_backend = scoring_backend
        self._code_fingerprint = (
            _digest(code_fingerprint, "code_fingerprint")
            if code_fingerprint is not None
            else None
        )
        self._data_snapshot_identity = (
            _digest(data_snapshot_identity, "data_snapshot_identity")
            if data_snapshot_identity is not None
            else None
        )
        self._repair_advisor: BoundedFormalizationAdvisor | None = None
        if model is not None:
            self._repair_advisor = BoundedFormalizationAdvisor(
                model, self.config.to_advisor_config()
            )

    def advise(
        self, request: FormalizationAutoencoderRequest
    ) -> AutoencoderAdviceResult:
        """Produce ranking, compression, introspection, and optional repairs."""

        if not isinstance(request, FormalizationAutoencoderRequest):
            raise AutoencoderAdvisorValidationError(
                "request must be a FormalizationAutoencoderRequest"
            )
        binding = request.checkpoint_binding
        if self._code_fingerprint is None:
            code_fingerprint = binding.code_fingerprint
        else:
            code_fingerprint = self._code_fingerprint
        if self._data_snapshot_identity is None:
            data_snapshot = binding.data_snapshot_identity
        else:
            data_snapshot = self._data_snapshot_identity
        binding.require_compatible(
            domain=request.artifact.domain,
            ontology_identity=request.ontology_identity,
            view_registry_identity=request.artifact.view_registry.identity.digest,
            feature_schema_version=request.features.schema_version,
            advisor_config_identity=self.config.digest,
            code_fingerprint=code_fingerprint,
            data_snapshot_identity=data_snapshot,
        )

        ranked_views = self.rank_views(request)
        ranked_premises = self.rank_premises(request)
        compression = self.compress(request, ranked_views=ranked_views)
        introspection = self.introspect(
            request,
            ranked_views=ranked_views,
            compression_plan=compression,
        )
        repair_result: AdvisorResult | None = None
        if request.repair_scope is not None:
            if self._repair_advisor is None:
                raise AutoencoderAdvisorValidationError(
                    "repair_scope was provided but no AdvisorModel is configured"
                )
            repair_result = self._repair_advisor.advise(
                FormalizationAdvisorRequest(
                    artifact=request.artifact,
                    features=request.features,
                    checkpoint=binding.checkpoint,
                    ontology_identity=request.ontology_identity,
                    repair_scope=request.repair_scope,
                )
            )
            if repair_result.authority != UNVERIFIED_AUTHORITY:
                raise AutoencoderAdvisorValidationError(
                    "repair result cannot claim proof or execution authority"
                )

        return AutoencoderAdviceResult(
            sample_id=request.artifact.sample_id,
            domain=request.artifact.domain,
            ranked_views=ranked_views,
            ranked_premises=ranked_premises,
            compression_plan=compression,
            introspection=introspection,
            config_identity=self.config.digest,
            checkpoint_binding_identity=binding.digest,
            input_features_identity=request.features.digest,
            input_artifact_identity=request.artifact.digest,
            ontology_identity=request.ontology_identity,
            repair_result=repair_result,
        )

    def rank_views(
        self, request: FormalizationAutoencoderRequest
    ) -> tuple[RankedView, ...]:
        """Rank registered views using backend scores or feature heuristics."""

        registry = request.artifact.view_registry
        views = tuple(registry.views)
        if not views:
            return ()
        view_ids = [item.view_id for item in views]
        families = {item.view_id: item.logic_family for item in views}
        scores = self._view_scores(request.features, view_ids, families)
        formula_counts: dict[str, int] = {}
        for formula in request.artifact.formulas:
            formula_counts[formula.view_id] = (
                formula_counts.get(formula.view_id, 0) + 1
            )
        # Blend sparse feature mass and formula occupancy into a stable score.
        for view in views:
            occupancy = float(formula_counts.get(view.view_id, 0))
            family_hits = sum(
                abs(value)
                for name, value in zip(
                    request.features.feature_names,
                    request.features.feature_values,
                )
                if view.logic_family in name or view.view_id in name
            )
            scores[view.view_id] = (
                float(scores.get(view.view_id, 0.0))
                + 0.5 * occupancy
                + 0.25 * family_hits
            )
        ordered = sorted(
            views,
            key=lambda item: (-scores.get(item.view_id, 0.0), item.view_id),
        )[: self.config.max_ranked_views]
        return tuple(
            RankedView(
                view_id=item.view_id,
                logic_family=item.logic_family,
                rank=index,
                score=round(float(scores.get(item.view_id, 0.0)), 12),
                reason="advisory_view_rank",
            )
            for index, item in enumerate(ordered)
        )

    def rank_premises(
        self, request: FormalizationAutoencoderRequest
    ) -> tuple[RankedPremise, ...]:
        """Rank grounded premise candidates; invent none from the model alone."""

        candidates = list(request.premise_candidates)
        if not candidates:
            # Derive advisory premises only from existing formulas that already
            # carry source grounding — never invent ungrounded statements.
            for formula in request.artifact.formulas:
                if not formula.source_ref_ids:
                    continue
                statement = self._formula_statement(formula)
                if not statement:
                    continue
                family = self._formula_family(request.artifact.view_registry, formula)
                candidates.append(
                    RankedPremise(
                        premise_id=f"premise:{formula.formula_id}",
                        statement=statement,
                        source_ref_ids=formula.source_ref_ids,
                        logic_family=family,
                        rank=0,
                        score=0.0,
                        formula_id=formula.formula_id,
                        reason="derived_from_formula",
                    )
                )
        if not candidates:
            return ()
        scores = self._premise_scores(
            request.features, [item.premise_id for item in candidates]
        )
        for index, premise in enumerate(candidates):
            feature_mass = sum(
                abs(value)
                for name, value in zip(
                    request.features.feature_names,
                    request.features.feature_values,
                )
                if premise.logic_family in name
                or premise.premise_id in name
                or (premise.formula_id and premise.formula_id in name)
            )
            scores[premise.premise_id] = (
                float(scores.get(premise.premise_id, premise.score))
                + 0.25 * feature_mass
                + 0.1 * len(premise.source_ref_ids)
            )
        ordered = sorted(
            candidates,
            key=lambda item: (
                -scores.get(item.premise_id, item.score),
                item.premise_id,
            ),
        )[: self.config.max_ranked_premises]
        return tuple(
            RankedPremise(
                premise_id=item.premise_id,
                statement=item.statement,
                source_ref_ids=item.source_ref_ids,
                logic_family=item.logic_family,
                rank=index,
                score=round(float(scores.get(item.premise_id, item.score)), 12),
                formula_id=item.formula_id,
                reason=item.reason or "advisory_premise_rank",
            )
            for index, item in enumerate(ordered)
        )

    def compress(
        self,
        request: FormalizationAutoencoderRequest,
        *,
        ranked_views: Sequence[RankedView] | None = None,
    ) -> CompressionPlan:
        """Select a bounded feature subset as compression guidance."""

        features = request.features
        pairs = list(zip(features.feature_names, features.feature_values))
        pairs.sort(key=lambda item: (-abs(float(item[1])), item[0]))
        budget = min(self.config.max_compression_features, len(pairs))
        retained = tuple(name for name, _ in pairs[:budget])
        dropped = tuple(name for name, _ in pairs[budget:])
        views = (
            tuple(item.view_id for item in ranked_views)
            if ranked_views is not None
            else tuple(
                item.view_id for item in self.rank_views(request)
            )
        )
        total = max(len(pairs), 1)
        ratio = float(total) / float(max(len(retained), 1))
        retained_values = [float(value) for name, value in pairs if name in retained]
        all_values = [float(value) for _, value in pairs]
        reconstruction = 1.0
        if all_values and retained_values:
            # Proxy reconstruction: mass retained under L1 relative to total.
            reconstruction = min(
                1.0,
                sum(abs(v) for v in retained_values)
                / max(sum(abs(v) for v in all_values), _SCORE_EPS),
            )
        return CompressionPlan(
            sample_id=features.sample_id,
            retained_feature_names=retained,
            dropped_feature_names=dropped,
            retained_view_ids=views[: self.config.max_ranked_views],
            estimated_compression_ratio=round(max(1.0, ratio), 12),
            reconstruction_score=round(reconstruction, 12),
        )

    def introspect(
        self,
        request: FormalizationAutoencoderRequest,
        *,
        ranked_views: Sequence[RankedView] | None = None,
        compression_plan: CompressionPlan | None = None,
    ) -> FormalizationIntrospection:
        """Emit domain-neutral introspection for ranking and reconstruction."""

        views = (
            tuple(ranked_views)
            if ranked_views is not None
            else self.rank_views(request)
        )
        plan = (
            compression_plan
            if compression_plan is not None
            else self.compress(request, ranked_views=views)
        )
        raw_scores = {item.view_id: item.score for item in views}
        distribution = _softmax(raw_scores) if raw_scores else {}
        # Observed occupancy from formulas is the "target" distribution.
        formula_counts: dict[str, float] = {}
        for formula in request.artifact.formulas:
            formula_counts[formula.view_id] = (
                formula_counts.get(formula.view_id, 0.0) + 1.0
            )
        total_formulas = sum(formula_counts.values()) or 1.0
        target_dist = {
            key: value / total_formulas for key, value in formula_counts.items()
        }
        for view_id in distribution:
            target_dist.setdefault(view_id, 0.0)
        for view_id in target_dist:
            distribution.setdefault(view_id, 0.0)

        predicted_family = (
            views[0].logic_family if views else "unspecified"
        )
        target_family = request.target_logic_family or predicted_family
        if request.target_logic_family and views:
            matching = [
                item for item in views if item.logic_family == target_family
            ]
            if matching:
                predicted_family = matching[0].logic_family
        family_scores: dict[str, float] = {}
        for item in views:
            family_scores[item.logic_family] = (
                family_scores.get(item.logic_family, 0.0) + item.score
            )
        family_probs = _softmax(family_scores)
        target_prob = family_probs.get(target_family, 0.0)
        others = [
            prob
            for family, prob in family_probs.items()
            if family != target_family
        ]
        best_other = max(others) if others else 0.0
        contributions = tuple(
            FeatureContribution(
                name=name,
                score=round(abs(float(value)), 12),
                kind="feature",
            )
            for name, value in zip(
                request.features.feature_names,
                request.features.feature_values,
            )
        )
        contributions = tuple(
            sorted(contributions, key=lambda item: (-item.score, item.name))[
                :8
            ]
        )
        focus: list[str] = []
        if plan.dropped_feature_names:
            focus.append("compression")
        if views and views[0].logic_family != target_family:
            focus.append("family_mismatch")
        if plan.reconstruction_score < 0.85:
            focus.append("reconstruction")
        if not focus:
            focus.append("stable")
        return FormalizationIntrospection(
            sample_id=request.artifact.sample_id,
            domain=request.artifact.domain,
            predicted_logic_family=predicted_family,
            target_logic_family=target_family,
            family_margin=round(target_prob - best_other, 12),
            reconstruction_score=plan.reconstruction_score,
            view_distribution=target_dist,
            predicted_view_distribution=distribution,
            top_feature_contributions=contributions,
            synthesis_focus=tuple(focus),
        )

    def _view_scores(
        self,
        features: FormalizationFeatures,
        view_ids: Sequence[str],
        logic_families: Mapping[str, str],
    ) -> dict[str, float]:
        scores = {view_id: 0.0 for view_id in view_ids}
        if self._scoring_backend is None:
            return scores
        try:
            raw = self._scoring_backend.score_views(
                features=features,
                view_ids=view_ids,
                logic_families=logic_families,
            )
        except Exception as exc:  # noqa: BLE001 - untrusted backend
            raise AutoencoderAdvisorValidationError(
                f"scoring backend failed for views: {exc}"
            ) from exc
        if not isinstance(raw, Mapping):
            raise AutoencoderAdvisorValidationError(
                "scoring backend must return a mapping of view scores"
            )
        for view_id in view_ids:
            if view_id in raw:
                scores[view_id] = _finite_score(raw[view_id], f"score[{view_id}]")
        return scores

    def _premise_scores(
        self,
        features: FormalizationFeatures,
        premise_ids: Sequence[str],
    ) -> dict[str, float]:
        scores = {premise_id: 0.0 for premise_id in premise_ids}
        if self._scoring_backend is None:
            return scores
        try:
            raw = self._scoring_backend.score_premises(
                features=features,
                premise_ids=premise_ids,
            )
        except Exception as exc:  # noqa: BLE001 - untrusted backend
            raise AutoencoderAdvisorValidationError(
                f"scoring backend failed for premises: {exc}"
            ) from exc
        if not isinstance(raw, Mapping):
            raise AutoencoderAdvisorValidationError(
                "scoring backend must return a mapping of premise scores"
            )
        for premise_id in premise_ids:
            if premise_id in raw:
                scores[premise_id] = _finite_score(
                    raw[premise_id], f"score[{premise_id}]"
                )
        return scores

    @staticmethod
    def _formula_statement(formula: FormalFormula) -> str:
        expression = thaw_json(formula.expression)
        if not isinstance(expression, Mapping):
            return formula.formula_id
        for key in ("statement", "text", "predicate"):
            value = expression.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:4_096]
        body = expression.get("body")
        if isinstance(body, Mapping):
            for key in ("statement", "text", "predicate"):
                value = body.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()[:4_096]
        operator = expression.get("operator")
        if isinstance(operator, str) and operator.strip():
            return operator.strip()[:4_096]
        return formula.formula_id

    @staticmethod
    def _formula_family(
        registry: ViewRegistry, formula: FormalFormula
    ) -> str:
        try:
            view: FormalizationView = registry.resolve(formula.view_id)
        except Exception:  # noqa: BLE001 - defensive for missing views
            return "unspecified"
        return view.logic_family


def build_code_fingerprint(module_paths: Sequence[str], *contents: str) -> str:
    """Deterministic code fingerprint from module paths and optional bodies.

    Callers typically pass the source of the advisor config/schema files so
    checkpoint bindings pin the exact code surface used for advice.
    """

    payload = {
        "module_paths": list(module_paths),
        "contents": list(contents),
    }
    return _content_digest(payload)


def build_data_snapshot_identity(
    sample_ids: Sequence[str],
    *,
    domain: str,
    split_manifest_digest: str = "",
) -> str:
    """Bind an immutable data snapshot used by a checkpoint head."""

    payload = {
        "domain": _identifier(domain, "domain"),
        "sample_ids": sorted(
            _identifier(item, "sample_ids") for item in sample_ids
        ),
        "split_manifest_digest": (
            _digest(split_manifest_digest, "split_manifest_digest")
            if split_manifest_digest
            else ""
        ),
    }
    return _content_digest(payload)


# Interface alias for FormalizationAutoencoderAdvisor@1 documentation.
FormalizationAutoencoderAdvisorV1 = FormalizationAutoencoderAdvisor


__all__ = [
    "AUTOENCODER_ADVICE_SCHEMA_VERSION",
    "AUTOENCODER_ADVISOR_CONFIG_SCHEMA_VERSION",
    "AUTOENCODER_CHECKPOINT_BINDING_SCHEMA_VERSION",
    "COMPRESSION_PLAN_SCHEMA_VERSION",
    "FEATURE_CONTRIBUTION_SCHEMA_VERSION",
    "FORMALIZATION_AUTOENCODER_ADVISOR_ID",
    "FORMALIZATION_AUTOENCODER_ADVISOR_VERSION",
    "INTROSPECTION_SCHEMA_VERSION",
    "RANKED_PREMISE_SCHEMA_VERSION",
    "RANKED_VIEW_SCHEMA_VERSION",
    "SPLIT_EXAMPLE_SCHEMA_VERSION",
    "SPLIT_MANIFEST_SCHEMA_VERSION",
    "UNVERIFIED_AUTHORITY",
    "AutoencoderAdviceResult",
    "AutoencoderAdvisorConfig",
    "AutoencoderAdvisorValidationError",
    "AutoencoderCheckpointBinding",
    "AutoencoderScoringBackend",
    "CompressionPlan",
    "FeatureContribution",
    "FormalizationAutoencoderAdvisor",
    "FormalizationAutoencoderAdvisorV1",
    "FormalizationAutoencoderRequest",
    "FormalizationIntrospection",
    "FormalizationSplitExample",
    "FormalizationSplitManifest",
    "PartitionName",
    "RankedPremise",
    "RankedView",
    "RankingKind",
    "SplitLeakageError",
    "build_code_fingerprint",
    "build_data_snapshot_identity",
]
