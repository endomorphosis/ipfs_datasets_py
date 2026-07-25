"""Bounded, authority-free learned assistance for formalization.

The model-facing protocol can suggest alternate formula expressions or small
JSON-pointer repairs.  It cannot construct a formalization artifact, mutate
source provenance, add assumptions, alter formula metadata, or claim a proof.
Every suggestion is decoded strictly, checked against an explicit repair
scope, reconstructed as a :class:`FormalFormula`, and returned as an
unverified candidate with complete invocation identities.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Final, Protocol, runtime_checkable

from ipfs_datasets_py.logic.ir_core.claims import (
    FrozenJSON,
    FrozenMap,
    freeze_json,
    thaw_json,
)
from ipfs_datasets_py.logic.ir_core.identity import (
    CanonicalIdentity,
    canonical_identity,
)

from .checkpoints import CheckpointManifest, validate_checkpoint_manifest
from .compiler import FormalizationArtifact
from .features import FormalizationFeatures, validate_source_free_features
from .samples import (
    FormalizationValidationError,
    _DIGEST_RE,
    _identifier,
    _mapping,
    _reject_unknown,
    _sequence,
    _text,
    _unique_identifiers,
)
from .views import FormalFormula, validate_view_artifacts


ADVISOR_CONFIG_SCHEMA_VERSION: Final = "formalization-advisor-config/v1"
ADVISOR_MODEL_REQUEST_SCHEMA_VERSION: Final = "formalization-advisor-request/v1"
FORMULA_SUGGESTION_SCHEMA_VERSION: Final = "formalization-formula-suggestion/v1"
FORMULA_REPAIR_SCHEMA_VERSION: Final = "formalization-formula-repair/v1"
ADVISOR_CANDIDATE_SCHEMA_VERSION: Final = "formalization-advisor-candidate/v1"
ADVISED_CANDIDATE_SCHEMA_VERSION: Final = "formalization-advised-candidate/v1"
ADVISOR_RESULT_SCHEMA_VERSION: Final = "formalization-advisor-result/v1"
REPAIR_SCOPE_SCHEMA_VERSION: Final = "formalization-repair-scope/v1"

_JSON_POINTER_TOKEN_RE = re.compile(r"^(?:[^~/]|~[01])*$")

# Domain adapters may add names but cannot remove these generic controls.
PROTECTED_SEMANTIC_FIELDS: Final = frozenset(
    {
        "assumption",
        "assumption_id",
        "assumption_ids",
        "assumptions",
        "grounding",
        "license",
        "license_expression",
        "license_id",
        "license_risk",
        "license_spdx",
        "modal_operator",
        "modality",
        "operator",
        "provenance",
        "review_status",
        "source",
        "source_ref",
        "source_ref_id",
        "source_ref_ids",
        "span_id",
        "span_ids",
        "trust",
        "trust_level",
        "trust_status",
        "trusted",
    }
)

_PROTECTED_PREFIXES: Final = (
    "assumption_",
    "license_",
    "modality_",
    "provenance_",
    "review_",
    "source_",
    "trust_",
)

_AUTHORITY_KEYS: Final = frozenset(
    {
        "authorization_status",
        "execution_result",
        "execution_status",
        "proof_result",
        "proof_status",
        "solver_result",
        "verification_result",
        "verification_status",
    }
)
_AUTHORITY_VALUES: Final = frozenset(
    {"authorized", "executed", "proved", "verified"}
)


class AdviceKind(str, Enum):
    """Whether a model candidate replaces expressions or applies small repairs."""

    FORMULA_CANDIDATE = "formula_candidate"
    REPAIR = "repair"


class AdvisorValidationError(FormalizationValidationError):
    """Raised when an advisor invocation or untrusted output is unsafe."""


def _positive_int(value: Any, field_name: str, *, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise AdvisorValidationError(f"{field_name} must be a positive integer")
    if value > maximum:
        raise AdvisorValidationError(
            f"{field_name} must not exceed the hard limit {maximum}"
        )
    return value


def _digest(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise AdvisorValidationError(
            f"{field_name} must be a lowercase sha256:<hex> digest"
        )
    return value


def _pointer(value: Any, field_name: str = "path") -> str:
    result = _text(value, field_name)
    if result == "/":
        raise AdvisorValidationError(f"{field_name} cannot address an empty key")
    if not result.startswith("/"):
        raise AdvisorValidationError(f"{field_name} must be a JSON pointer")
    tokens = result[1:].split("/")
    if any(not _JSON_POINTER_TOKEN_RE.fullmatch(token) for token in tokens):
        raise AdvisorValidationError(f"{field_name} is not a valid JSON pointer")
    return result


def _pointer_tokens(path: str) -> tuple[str, ...]:
    return tuple(
        token.replace("~1", "/").replace("~0", "~")
        for token in path[1:].split("/")
    )


def _json_size(value: Any) -> int:
    try:
        return len(
            json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        )
    except (TypeError, ValueError) as exc:
        raise AdvisorValidationError(
            "advisor output must be finite JSON data"
        ) from exc


def _json_shape(value: Any) -> tuple[int, int]:
    """Return ``(node_count, maximum_depth)`` for a JSON value."""

    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise AdvisorValidationError("expression keys must be strings")
        child_shapes = [_json_shape(item) for item in value.values()]
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        child_shapes = [_json_shape(item) for item in value]
    else:
        child_shapes = []
    return (
        1 + sum(nodes for nodes, _ in child_shapes),
        1 + max((depth for _, depth in child_shapes), default=0),
    )


def _normalized_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _is_protected_key(key: str, protected: frozenset[str]) -> bool:
    normalized = _normalized_key(key)
    return normalized in protected or normalized.startswith(_PROTECTED_PREFIXES)


def _protected_projection(
    value: Any,
    protected: frozenset[str],
    *,
    path: str = "",
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key)
            escaped = key.replace("~", "~0").replace("/", "~1")
            child_path = f"{path}/{escaped}"
            if _is_protected_key(key, protected):
                result[child_path] = child
            result.update(
                _protected_projection(child, protected, path=child_path)
            )
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for index, child in enumerate(value):
            result.update(
                _protected_projection(child, protected, path=f"{path}/{index}")
            )
    return result


def _reject_authority_claims(value: Any, *, path: str = "") -> None:
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = _normalized_key(str(raw_key))
            child_path = f"{path}/{raw_key}"
            if key in _AUTHORITY_KEYS:
                raise AdvisorValidationError(
                    f"candidate cannot claim proof or execution authority at {child_path}"
                )
            if key == "status" and isinstance(child, str):
                if _normalized_key(child) in _AUTHORITY_VALUES:
                    raise AdvisorValidationError(
                        "candidate cannot claim proof or execution authority "
                        f"at {child_path}"
                    )
            _reject_authority_claims(child, path=child_path)
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for index, child in enumerate(value):
            _reject_authority_claims(child, path=f"{path}/{index}")


def _changed_paths(before: Any, after: Any, *, path: str = "") -> set[str]:
    if type(before) is not type(after):
        return {path or "/"}
    if isinstance(before, Mapping):
        before_keys = set(before)
        after_keys = set(after)
        result = {
            f"{path}/{str(key).replace('~', '~0').replace('/', '~1')}"
            for key in before_keys ^ after_keys
        }
        for key in before_keys & after_keys:
            escaped = str(key).replace("~", "~0").replace("/", "~1")
            result.update(
                _changed_paths(
                    before[key],
                    after[key],
                    path=f"{path}/{escaped}",
                )
            )
        return result
    if isinstance(before, Sequence) and not isinstance(
        before, (str, bytes, bytearray)
    ):
        if len(before) != len(after):
            return {path or "/"}
        result: set[str] = set()
        for index, (old, new) in enumerate(zip(before, after)):
            result.update(_changed_paths(old, new, path=f"{path}/{index}"))
        return result
    return set() if before == after else {path or "/"}


@dataclass(frozen=True, slots=True)
class RepairScope:
    """Explicit formula IDs and JSON subtrees an invocation may change."""

    formula_ids: tuple[str, ...]
    allowed_paths: tuple[str, ...]
    max_operations: int = 1
    schema_version: str = REPAIR_SCOPE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "formula_ids",
            _unique_identifiers(self.formula_ids, "formula_ids"),
        )
        if not self.formula_ids:
            raise AdvisorValidationError("repair scope requires formula_ids")
        if isinstance(self.allowed_paths, (str, bytes, bytearray)):
            raise AdvisorValidationError("allowed_paths must be a sequence")
        paths = tuple(sorted(_pointer(item, "allowed_path") for item in self.allowed_paths))
        if not paths:
            raise AdvisorValidationError("repair scope requires allowed_paths")
        if len(paths) != len(set(paths)):
            raise AdvisorValidationError("allowed_paths must be unique")
        object.__setattr__(self, "allowed_paths", paths)
        object.__setattr__(
            self,
            "max_operations",
            _positive_int(self.max_operations, "max_operations", maximum=256),
        )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != REPAIR_SCOPE_SCHEMA_VERSION:
            raise AdvisorValidationError(
                f"unsupported repair scope schema: {self.schema_version!r}"
            )

    def allows(self, formula_id: str, path: str) -> bool:
        return formula_id in self.formula_ids and any(
            path == allowed or path.startswith(f"{allowed}/")
            for allowed in self.allowed_paths
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed_paths": list(self.allowed_paths),
            "formula_ids": list(self.formula_ids),
            "max_operations": self.max_operations,
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
    def from_dict(cls, value: Mapping[str, Any]) -> "RepairScope":
        value = _mapping(value, "repair scope")
        _reject_unknown(
            value,
            frozenset(
                {
                    "allowed_paths",
                    "formula_ids",
                    "max_operations",
                    "schema_version",
                }
            ),
            "repair scope",
        )
        return cls(
            formula_ids=tuple(
                _sequence(value.get("formula_ids", ()), "formula_ids")
            ),
            allowed_paths=tuple(
                _sequence(value.get("allowed_paths", ()), "allowed_paths")
            ),
            max_operations=value.get("max_operations", 1),
            schema_version=value.get(
                "schema_version", REPAIR_SCOPE_SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_json(
        cls, value: str | bytes | bytearray
    ) -> "RepairScope":
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, UnicodeDecodeError) as exc:
            raise AdvisorValidationError(
                "repair scope must be valid JSON"
            ) from exc
        return cls.from_dict(_mapping(decoded, "repair scope"))


@dataclass(frozen=True, slots=True)
class AdvisorConfig:
    """Immutable hard bounds applied before any candidate is returned."""

    advisor_id: str
    advisor_version: str
    config_id: str = "default"
    max_candidates: int = 4
    max_formulas_per_candidate: int = 8
    max_expression_nodes: int = 512
    max_expression_depth: int = 32
    max_expression_bytes: int = 16_384
    protected_field_names: tuple[str, ...] = ()
    schema_version: str = ADVISOR_CONFIG_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "advisor_id", _identifier(self.advisor_id, "advisor_id")
        )
        object.__setattr__(
            self,
            "advisor_version",
            _identifier(self.advisor_version, "advisor_version"),
        )
        object.__setattr__(self, "config_id", _identifier(self.config_id, "config_id"))
        for name, maximum in (
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
            _normalized_key(_identifier(item, "protected_field_names"))
            for item in self.protected_field_names
        )
        object.__setattr__(
            self,
            "protected_field_names",
            tuple(sorted(PROTECTED_SEMANTIC_FIELDS | set(extras))),
        )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != ADVISOR_CONFIG_SCHEMA_VERSION:
            raise AdvisorValidationError(
                f"unsupported advisor config schema: {self.schema_version!r}"
            )

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.to_dict(),
            domain="formalization-advisor-config",
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
            "max_expression_bytes": self.max_expression_bytes,
            "max_expression_depth": self.max_expression_depth,
            "max_expression_nodes": self.max_expression_nodes,
            "max_formulas_per_candidate": self.max_formulas_per_candidate,
            "protected_field_names": list(self.protected_field_names),
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
    def from_dict(cls, value: Mapping[str, Any]) -> "AdvisorConfig":
        value = _mapping(value, "advisor config")
        allowed = frozenset(
            {
                "advisor_id",
                "advisor_version",
                "config_id",
                "max_candidates",
                "max_expression_bytes",
                "max_expression_depth",
                "max_expression_nodes",
                "max_formulas_per_candidate",
                "protected_field_names",
                "schema_version",
            }
        )
        _reject_unknown(value, allowed, "advisor config")
        return cls(
            advisor_id=value.get("advisor_id", ""),
            advisor_version=value.get("advisor_version", ""),
            config_id=value.get("config_id", "default"),
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
                "schema_version", ADVISOR_CONFIG_SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_json(
        cls, value: str | bytes | bytearray
    ) -> "AdvisorConfig":
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, UnicodeDecodeError) as exc:
            raise AdvisorValidationError(
                "advisor config must be valid JSON"
            ) from exc
        return cls.from_dict(_mapping(decoded, "advisor config"))


@dataclass(frozen=True, slots=True)
class FormulaSuggestion:
    """A complete alternate expression for one existing formula."""

    formula_id: str
    expression: FrozenJSON
    schema_version: str = FORMULA_SUGGESTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "formula_id", _identifier(self.formula_id, "formula_id")
        )
        try:
            object.__setattr__(self, "expression", freeze_json(self.expression))
        except (TypeError, ValueError) as exc:
            raise AdvisorValidationError("suggestion expression must be JSON") from exc
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != FORMULA_SUGGESTION_SCHEMA_VERSION:
            raise AdvisorValidationError(
                f"unsupported formula suggestion schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "expression": thaw_json(self.expression),
            "formula_id": self.formula_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FormulaSuggestion":
        value = _mapping(value, "formula suggestion")
        _reject_unknown(
            value,
            frozenset({"expression", "formula_id", "schema_version"}),
            "formula suggestion",
        )
        return cls(
            formula_id=value.get("formula_id", ""),
            expression=value.get("expression"),
            schema_version=value.get(
                "schema_version", FORMULA_SUGGESTION_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class FormulaRepair:
    """One replacement at an existing JSON-pointer path."""

    formula_id: str
    path: str
    replacement: FrozenJSON
    schema_version: str = FORMULA_REPAIR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "formula_id", _identifier(self.formula_id, "formula_id")
        )
        object.__setattr__(self, "path", _pointer(self.path))
        try:
            object.__setattr__(self, "replacement", freeze_json(self.replacement))
        except (TypeError, ValueError) as exc:
            raise AdvisorValidationError("repair replacement must be JSON") from exc
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != FORMULA_REPAIR_SCHEMA_VERSION:
            raise AdvisorValidationError(
                f"unsupported formula repair schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "formula_id": self.formula_id,
            "path": self.path,
            "replacement": thaw_json(self.replacement),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FormulaRepair":
        value = _mapping(value, "formula repair")
        _reject_unknown(
            value,
            frozenset(
                {"formula_id", "path", "replacement", "schema_version"}
            ),
            "formula repair",
        )
        return cls(
            formula_id=value.get("formula_id", ""),
            path=value.get("path", ""),
            replacement=value.get("replacement"),
            schema_version=value.get(
                "schema_version", FORMULA_REPAIR_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class AdvisorCandidate:
    """Strict wire record returned by an untrusted model provider."""

    candidate_id: str
    kind: AdviceKind
    suggestions: tuple[FormulaSuggestion, ...] = ()
    repairs: tuple[FormulaRepair, ...] = ()
    schema_version: str = ADVISOR_CANDIDATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "candidate_id", _identifier(self.candidate_id, "candidate_id")
        )
        try:
            kind = self.kind if isinstance(self.kind, AdviceKind) else AdviceKind(self.kind)
        except (TypeError, ValueError) as exc:
            raise AdvisorValidationError(f"unknown advice kind: {self.kind!r}") from exc
        object.__setattr__(self, "kind", kind)
        suggestions = tuple(
            item
            if isinstance(item, FormulaSuggestion)
            else FormulaSuggestion.from_dict(_mapping(item, "formula suggestion"))
            for item in self.suggestions
        )
        repairs = tuple(
            item
            if isinstance(item, FormulaRepair)
            else FormulaRepair.from_dict(_mapping(item, "formula repair"))
            for item in self.repairs
        )
        if kind is AdviceKind.FORMULA_CANDIDATE:
            if not suggestions or repairs:
                raise AdvisorValidationError(
                    "formula candidates require suggestions and no repairs"
                )
        elif not repairs or suggestions:
            raise AdvisorValidationError(
                "repair candidates require repairs and no suggestions"
            )
        ids = [
            item.formula_id for item in (suggestions if suggestions else repairs)
        ]
        if len(ids) != len(set(ids)) and suggestions:
            raise AdvisorValidationError(
                "a formula candidate may suggest each formula only once"
            )
        repair_targets = [(item.formula_id, item.path) for item in repairs]
        if len(repair_targets) != len(set(repair_targets)):
            raise AdvisorValidationError(
                "a repair candidate may replace each formula path only once"
            )
        object.__setattr__(self, "suggestions", suggestions)
        object.__setattr__(self, "repairs", repairs)
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != ADVISOR_CANDIDATE_SCHEMA_VERSION:
            raise AdvisorValidationError(
                f"unsupported advisor candidate schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "kind": self.kind.value,
            "repairs": [item.to_dict() for item in self.repairs],
            "schema_version": self.schema_version,
            "suggestions": [item.to_dict() for item in self.suggestions],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AdvisorCandidate":
        value = _mapping(value, "advisor candidate")
        _reject_unknown(
            value,
            frozenset(
                {
                    "candidate_id",
                    "kind",
                    "repairs",
                    "schema_version",
                    "suggestions",
                }
            ),
            "advisor candidate",
        )
        return cls(
            candidate_id=value.get("candidate_id", ""),
            kind=value.get("kind", ""),
            suggestions=tuple(
                FormulaSuggestion.from_dict(_mapping(item, "formula suggestion"))
                for item in _sequence(value.get("suggestions", ()), "suggestions")
            ),
            repairs=tuple(
                FormulaRepair.from_dict(_mapping(item, "formula repair"))
                for item in _sequence(value.get("repairs", ()), "repairs")
            ),
            schema_version=value.get(
                "schema_version", ADVISOR_CANDIDATE_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class AdvisorModelRequest:
    """Source-free, authority-free model input for one invocation."""

    sample_id: str
    domain: str
    declaration_digest: str
    feature_names: tuple[str, ...]
    feature_values: tuple[float, ...]
    formulas: tuple[FrozenMap, ...]
    repair_scope: RepairScope
    checkpoint_identity: str
    schema_version: str = ADVISOR_MODEL_REQUEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "sample_id", _identifier(self.sample_id, "sample_id"))
        object.__setattr__(self, "domain", _identifier(self.domain, "domain"))
        object.__setattr__(
            self,
            "declaration_digest",
            _digest(self.declaration_digest, "declaration_digest"),
        )
        object.__setattr__(
            self,
            "feature_names",
            tuple(_text(item, "feature_names") for item in self.feature_names),
        )
        if (
            not isinstance(self.feature_values, tuple)
            or len(self.feature_names) != len(self.feature_values)
        ):
            raise AdvisorValidationError(
                "feature names and values must be equal immutable tuples"
            )
        if not isinstance(self.repair_scope, RepairScope):
            raise AdvisorValidationError("repair_scope must be a RepairScope")
        object.__setattr__(
            self,
            "formulas",
            tuple(
                item
                if isinstance(item, FrozenMap)
                else FrozenMap(_mapping(item, "model formula"))
                for item in self.formulas
            ),
        )
        object.__setattr__(
            self,
            "checkpoint_identity",
            _digest(self.checkpoint_identity, "checkpoint_identity"),
        )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != ADVISOR_MODEL_REQUEST_SCHEMA_VERSION:
            raise AdvisorValidationError(
                f"unsupported advisor request schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_identity": self.checkpoint_identity,
            "declaration_digest": self.declaration_digest,
            "domain": self.domain,
            "feature_names": list(self.feature_names),
            "feature_values": list(self.feature_values),
            "formulas": [item.to_dict() for item in self.formulas],
            "repair_scope": self.repair_scope.to_dict(),
            "sample_id": self.sample_id,
            "schema_version": self.schema_version,
        }

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.to_dict(),
            domain=f"formalization-advisor-request:{self.domain}",
            schema_version=self.schema_version,
            collection_semantics={
                "/repair_scope/allowed_paths": "set-like",
                "/repair_scope/formula_ids": "set-like",
            },
        )

    @property
    def digest(self) -> str:
        return self.identity.digest


@runtime_checkable
class AdvisorModel(Protocol):
    """Injectable model backend; outputs remain untrusted until validated."""

    def generate_candidates(
        self, request: AdvisorModelRequest
    ) -> Sequence[AdvisorCandidate | Mapping[str, Any]]:
        """Return candidate wire records without proof or execution authority."""


@dataclass(frozen=True, slots=True)
class FormalizationAdvisorRequest:
    """Trusted wrapper input joining deterministic and learned dependencies."""

    artifact: FormalizationArtifact
    features: FormalizationFeatures
    checkpoint: CheckpointManifest
    ontology_identity: str
    repair_scope: RepairScope

    def __post_init__(self) -> None:
        if not isinstance(self.artifact, FormalizationArtifact):
            raise AdvisorValidationError(
                "artifact must be a FormalizationArtifact"
            )
        self.artifact.validate()
        object.__setattr__(
            self, "features", validate_source_free_features(self.features)
        )
        object.__setattr__(
            self, "checkpoint", validate_checkpoint_manifest(self.checkpoint)
        )
        object.__setattr__(
            self,
            "ontology_identity",
            _digest(self.ontology_identity, "ontology_identity"),
        )
        if not isinstance(self.repair_scope, RepairScope):
            raise AdvisorValidationError("repair_scope must be a RepairScope")
        if (
            self.features.sample_id != self.artifact.sample_id
            or self.features.domain != self.artifact.domain
            or self.features.declaration_digest
            != self.artifact.declaration_digest
        ):
            raise AdvisorValidationError(
                "features do not identify the input artifact declaration"
            )
        known_formula_ids = {item.formula_id for item in self.artifact.formulas}
        unknown = set(self.repair_scope.formula_ids) - known_formula_ids
        if unknown:
            raise AdvisorValidationError(
                "repair scope references unknown formulas: "
                + ", ".join(sorted(unknown))
            )
        self.checkpoint.require_compatible(
            domain=self.artifact.domain,
            ontology_identity=self.ontology_identity,
            view_registry_identity=self.artifact.view_registry.identity.digest,
            feature_schema_version=self.features.schema_version,
        )

    def model_request(self) -> AdvisorModelRequest:
        scoped = set(self.repair_scope.formula_ids)
        formulas = tuple(
            FrozenMap(
                {
                    "expression": thaw_json(item.expression),
                    "formula_id": item.formula_id,
                    "view_id": item.view_id,
                }
            )
            for item in self.artifact.formulas
            if item.formula_id in scoped
        )
        return AdvisorModelRequest(
            sample_id=self.artifact.sample_id,
            domain=self.artifact.domain,
            declaration_digest=self.artifact.declaration_digest,
            feature_names=self.features.feature_names,
            feature_values=self.features.feature_values,
            formulas=formulas,
            repair_scope=self.repair_scope,
            checkpoint_identity=self.checkpoint.digest,
        )


@dataclass(frozen=True, slots=True)
class AdvisedCandidate:
    """Typed, bounded formulas that remain unverified candidate material."""

    candidate_id: str
    kind: AdviceKind
    formulas: tuple[FormalFormula, ...]
    changed_formula_ids: tuple[str, ...]
    schema_version: str = ADVISED_CANDIDATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "candidate_id", _identifier(self.candidate_id, "candidate_id")
        )
        try:
            kind = (
                self.kind
                if isinstance(self.kind, AdviceKind)
                else AdviceKind(self.kind)
            )
        except (TypeError, ValueError) as exc:
            raise AdvisorValidationError(
                f"unknown advice kind: {self.kind!r}"
            ) from exc
        object.__setattr__(self, "kind", kind)
        formulas = tuple(
            item
            if isinstance(item, FormalFormula)
            else FormalFormula.from_dict(_mapping(item, "formal formula"))
            for item in self.formulas
        )
        formula_ids = [item.formula_id for item in formulas]
        if not formulas or len(formula_ids) != len(set(formula_ids)):
            raise AdvisorValidationError(
                "advised candidate formulas must be non-empty with unique IDs"
            )
        object.__setattr__(
            self,
            "formulas",
            tuple(sorted(formulas, key=lambda item: item.formula_id)),
        )
        changed = _unique_identifiers(
            self.changed_formula_ids, "changed_formula_ids"
        )
        if not changed or not set(changed).issubset(formula_ids):
            raise AdvisorValidationError(
                "changed_formula_ids must identify candidate formulas"
            )
        object.__setattr__(self, "changed_formula_ids", changed)
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != ADVISED_CANDIDATE_SCHEMA_VERSION:
            raise AdvisorValidationError(
                f"unsupported advised candidate schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": "unverified_candidate_only",
            "candidate_id": self.candidate_id,
            "changed_formula_ids": list(self.changed_formula_ids),
            "formulas": [item.to_dict() for item in self.formulas],
            "kind": self.kind.value,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AdvisedCandidate":
        value = _mapping(value, "advised candidate")
        _reject_unknown(
            value,
            frozenset(
                {
                    "authority",
                    "candidate_id",
                    "changed_formula_ids",
                    "formulas",
                    "kind",
                    "schema_version",
                }
            ),
            "advised candidate",
        )
        if value.get("authority") != "unverified_candidate_only":
            raise AdvisorValidationError(
                "advised candidate cannot claim proof or execution authority"
            )
        return cls(
            candidate_id=value.get("candidate_id", ""),
            kind=value.get("kind", ""),
            formulas=tuple(
                FormalFormula.from_dict(_mapping(item, "formal formula"))
                for item in _sequence(value.get("formulas", ()), "formulas")
            ),
            changed_formula_ids=tuple(
                _sequence(
                    value.get("changed_formula_ids", ()),
                    "changed_formula_ids",
                )
            ),
            schema_version=value.get(
                "schema_version", ADVISED_CANDIDATE_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class AdvisorResult:
    """Candidate collection and the complete identities of its invocation."""

    candidates: tuple[AdvisedCandidate, ...]
    model_identity: str
    config_identity: str
    checkpoint_identity: str
    input_request_identity: str
    input_artifact_identity: str
    input_features_identity: str
    ontology_identity: str
    schema_version: str = ADVISOR_RESULT_SCHEMA_VERSION
    authority: str = "unverified_candidate_only"

    def __post_init__(self) -> None:
        candidates = tuple(
            item
            if isinstance(item, AdvisedCandidate)
            else AdvisedCandidate.from_dict(_mapping(item, "advised candidate"))
            for item in self.candidates
        )
        candidate_ids = [item.candidate_id for item in candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise AdvisorValidationError("advised candidate IDs must be unique")
        object.__setattr__(
            self,
            "candidates",
            tuple(sorted(candidates, key=lambda item: item.candidate_id)),
        )
        for name in (
            "model_identity",
            "config_identity",
            "checkpoint_identity",
            "input_request_identity",
            "input_artifact_identity",
            "input_features_identity",
            "ontology_identity",
        ):
            object.__setattr__(self, name, _digest(getattr(self, name), name))
        if self.authority != "unverified_candidate_only":
            raise AdvisorValidationError(
                "advisor results cannot claim proof or execution authority"
            )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != ADVISOR_RESULT_SCHEMA_VERSION:
            raise AdvisorValidationError(
                f"unsupported advisor result schema: {self.schema_version!r}"
            )

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.to_dict(),
            domain="formalization-advisor-result",
            schema_version=self.schema_version,
            collection_semantics={"/candidates": "set-like"},
        )

    @property
    def digest(self) -> str:
        return self.identity.digest

    @property
    def input_identity(self) -> str:
        """Compatibility spelling for the complete model-request identity."""

        return self.input_request_identity

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "candidates": [item.to_dict() for item in self.candidates],
            "checkpoint_identity": self.checkpoint_identity,
            "config_identity": self.config_identity,
            "input_artifact_identity": self.input_artifact_identity,
            "input_features_identity": self.input_features_identity,
            "input_request_identity": self.input_request_identity,
            "model_identity": self.model_identity,
            "ontology_identity": self.ontology_identity,
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
    def from_dict(cls, value: Mapping[str, Any]) -> "AdvisorResult":
        value = _mapping(value, "advisor result")
        _reject_unknown(
            value,
            frozenset(
                {
                    "authority",
                    "candidates",
                    "checkpoint_identity",
                    "config_identity",
                    "input_artifact_identity",
                    "input_features_identity",
                    "input_request_identity",
                    "model_identity",
                    "ontology_identity",
                    "schema_version",
                }
            ),
            "advisor result",
        )
        return cls(
            candidates=tuple(
                AdvisedCandidate.from_dict(_mapping(item, "advised candidate"))
                for item in _sequence(value.get("candidates", ()), "candidates")
            ),
            model_identity=value.get("model_identity", ""),
            config_identity=value.get("config_identity", ""),
            checkpoint_identity=value.get("checkpoint_identity", ""),
            input_request_identity=value.get("input_request_identity", ""),
            input_artifact_identity=value.get("input_artifact_identity", ""),
            input_features_identity=value.get("input_features_identity", ""),
            ontology_identity=value.get("ontology_identity", ""),
            schema_version=value.get(
                "schema_version", ADVISOR_RESULT_SCHEMA_VERSION
            ),
            authority=value.get("authority", ""),
        )

    @classmethod
    def from_json(
        cls, value: str | bytes | bytearray
    ) -> "AdvisorResult":
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, UnicodeDecodeError) as exc:
            raise AdvisorValidationError(
                "advisor result must be valid JSON"
            ) from exc
        return cls.from_dict(_mapping(decoded, "advisor result"))


@runtime_checkable
class FormalizationAdvisor(Protocol):
    """Structural interface implemented by bounded advisor wrappers."""

    def advise(self, request: FormalizationAdvisorRequest) -> AdvisorResult:
        """Return typed candidates without modifying deterministic input."""


def _replace_at_pointer(expression: Any, path: str, replacement: Any) -> Any:
    root = thaw_json(freeze_json(expression))
    tokens = _pointer_tokens(path)
    current = root
    for token in tokens[:-1]:
        if isinstance(current, dict):
            if token not in current:
                raise AdvisorValidationError(
                    f"repair path does not exist: {path}"
                )
            current = current[token]
        elif isinstance(current, list):
            try:
                index = int(token)
            except ValueError as exc:
                raise AdvisorValidationError(
                    f"repair path does not exist: {path}"
                ) from exc
            if index < 0 or index >= len(current):
                raise AdvisorValidationError(
                    f"repair path does not exist: {path}"
                )
            current = current[index]
        else:
            raise AdvisorValidationError(f"repair path does not exist: {path}")
    final = tokens[-1]
    if isinstance(current, dict):
        if final not in current:
            raise AdvisorValidationError(f"repair path does not exist: {path}")
        current[final] = thaw_json(freeze_json(replacement))
    elif isinstance(current, list):
        try:
            index = int(final)
        except ValueError as exc:
            raise AdvisorValidationError(
                f"repair path does not exist: {path}"
            ) from exc
        if index < 0 or index >= len(current):
            raise AdvisorValidationError(f"repair path does not exist: {path}")
        current[index] = thaw_json(freeze_json(replacement))
    else:
        raise AdvisorValidationError(f"repair path does not exist: {path}")
    return root


class BoundedFormalizationAdvisor:
    """Validate an untrusted backend behind immutable advisor contracts."""

    def __init__(self, model: AdvisorModel, config: AdvisorConfig) -> None:
        method = getattr(model, "generate_candidates", None)
        if not callable(method):
            raise TypeError("model must implement generate_candidates")
        if not isinstance(config, AdvisorConfig):
            raise TypeError("config must be an AdvisorConfig")
        self._model = model
        self.config = AdvisorConfig.from_dict(config.to_dict())

    def advise(self, request: FormalizationAdvisorRequest) -> AdvisorResult:
        if not isinstance(request, FormalizationAdvisorRequest):
            raise AdvisorValidationError(
                "request must be a FormalizationAdvisorRequest"
            )
        model_request = request.model_request()
        model_output = self._model.generate_candidates(model_request)
        if isinstance(model_output, (str, bytes, bytearray, Mapping)):
            raise AdvisorValidationError(
                "model must return a sequence of candidate records"
            )
        if not isinstance(model_output, Sequence):
            raise AdvisorValidationError(
                "model must return a sequence of candidate records"
            )
        if len(model_output) > self.config.max_candidates:
            raise AdvisorValidationError(
                f"model returned more than {self.config.max_candidates} candidates"
            )
        decoded = tuple(
            item
            if isinstance(item, AdvisorCandidate)
            else AdvisorCandidate.from_dict(_mapping(item, "advisor candidate"))
            for item in model_output
        )
        candidate_ids = [item.candidate_id for item in decoded]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise AdvisorValidationError("candidate IDs must be unique")
        validated = tuple(
            self._validate_candidate(item, request) for item in decoded
        )
        return AdvisorResult(
            candidates=validated,
            model_identity=request.checkpoint.model_identity,
            config_identity=self.config.digest,
            checkpoint_identity=request.checkpoint.digest,
            input_request_identity=model_request.digest,
            input_artifact_identity=request.artifact.digest,
            input_features_identity=request.features.digest,
            ontology_identity=request.ontology_identity,
        )

    def _validate_candidate(
        self,
        candidate: AdvisorCandidate,
        request: FormalizationAdvisorRequest,
    ) -> AdvisedCandidate:
        count = len(candidate.suggestions) or len(candidate.repairs)
        if count > self.config.max_formulas_per_candidate:
            raise AdvisorValidationError(
                "candidate exceeds max_formulas_per_candidate"
            )
        if candidate.kind is AdviceKind.REPAIR and (
            len(candidate.repairs) > request.repair_scope.max_operations
        ):
            raise AdvisorValidationError("candidate exceeds repair scope operation bound")

        baseline = {
            item.formula_id: item for item in request.artifact.formulas
        }
        expressions = {
            key: thaw_json(value.expression) for key, value in baseline.items()
        }
        changed_ids: set[str] = set()

        if candidate.kind is AdviceKind.FORMULA_CANDIDATE:
            for suggestion in candidate.suggestions:
                old = baseline.get(suggestion.formula_id)
                if old is None:
                    raise AdvisorValidationError(
                        f"candidate references unknown formula {suggestion.formula_id!r}"
                    )
                new_expression = thaw_json(suggestion.expression)
                changed = _changed_paths(
                    thaw_json(old.expression), new_expression
                )
                if not changed:
                    raise AdvisorValidationError(
                        "formula suggestion must change at least one value"
                    )
                disallowed = {
                    path
                    for path in changed
                    if not request.repair_scope.allows(old.formula_id, path)
                }
                if disallowed:
                    raise AdvisorValidationError(
                        "formula suggestion exceeds repair scope: "
                        + ", ".join(sorted(disallowed))
                    )
                expressions[old.formula_id] = new_expression
                changed_ids.add(old.formula_id)
        else:
            for repair in candidate.repairs:
                if not request.repair_scope.allows(
                    repair.formula_id, repair.path
                ):
                    raise AdvisorValidationError(
                        f"repair exceeds scope: {repair.formula_id}{repair.path}"
                    )
                if repair.formula_id not in baseline:
                    raise AdvisorValidationError(
                        f"repair references unknown formula {repair.formula_id!r}"
                    )
                expressions[repair.formula_id] = _replace_at_pointer(
                    expressions[repair.formula_id],
                    repair.path,
                    repair.replacement,
                )
                changed_ids.add(repair.formula_id)

        protected = frozenset(self.config.protected_field_names)
        formulas: list[FormalFormula] = []
        for formula_id, old in baseline.items():
            expression = expressions[formula_id]
            if formula_id in changed_ids:
                old_projection = _protected_projection(
                    thaw_json(old.expression), protected
                )
                new_projection = _protected_projection(expression, protected)
                if old_projection != new_projection:
                    raise AdvisorValidationError(
                        "candidate cannot alter provenance, assumptions, "
                        "modality, trust, review, or license fields"
                    )
                _reject_authority_claims(expression)
                nodes, depth = _json_shape(expression)
                if nodes > self.config.max_expression_nodes:
                    raise AdvisorValidationError(
                        "candidate expression exceeds node bound"
                    )
                if depth > self.config.max_expression_depth:
                    raise AdvisorValidationError(
                        "candidate expression exceeds depth bound"
                    )
                if _json_size(expression) > self.config.max_expression_bytes:
                    raise AdvisorValidationError(
                        "candidate expression exceeds byte bound"
                    )
            try:
                formulas.append(replace(old, expression=expression))
            except (TypeError, ValueError) as exc:
                raise AdvisorValidationError(
                    f"candidate formula {formula_id!r} failed type/schema validation"
                ) from exc

        # Re-run all shared view/type/reference checks over the reconstructed
        # candidate.  No provenance binding or formula field came from the model.
        validate_view_artifacts(
            registry=request.artifact.view_registry,
            symbol_table=request.artifact.symbol_table,
            formulas=tuple(formulas),
            links=request.artifact.cross_view_links,
            source_ref_ids=tuple(
                item.ref_id for item in request.artifact.source_map.sources
            ),
            span_ids=tuple(
                item.span_id for item in request.artifact.source_map.spans
            ),
            assumption_ids=tuple(
                item.assumption_id for item in request.artifact.assumptions
            ),
        )
        return AdvisedCandidate(
            candidate_id=candidate.candidate_id,
            kind=candidate.kind,
            formulas=tuple(formulas),
            changed_formula_ids=tuple(sorted(changed_ids)),
        )


# Explicit long spellings make the generic ownership clear to domain wrappers.
FormalizationAdvisorConfig = AdvisorConfig
FormalizationAdvice = AdvisorResult
FormalizationAdvisorModel = AdvisorModel


__all__ = [
    "ADVISOR_CANDIDATE_SCHEMA_VERSION",
    "ADVISOR_CONFIG_SCHEMA_VERSION",
    "ADVISOR_MODEL_REQUEST_SCHEMA_VERSION",
    "ADVISOR_RESULT_SCHEMA_VERSION",
    "ADVISED_CANDIDATE_SCHEMA_VERSION",
    "FORMULA_REPAIR_SCHEMA_VERSION",
    "FORMULA_SUGGESTION_SCHEMA_VERSION",
    "PROTECTED_SEMANTIC_FIELDS",
    "REPAIR_SCOPE_SCHEMA_VERSION",
    "AdviceKind",
    "AdvisedCandidate",
    "AdvisorCandidate",
    "AdvisorConfig",
    "AdvisorModel",
    "AdvisorModelRequest",
    "AdvisorResult",
    "AdvisorValidationError",
    "BoundedFormalizationAdvisor",
    "FormalizationAdvice",
    "FormalizationAdvisor",
    "FormalizationAdvisorConfig",
    "FormalizationAdvisorModel",
    "FormalizationAdvisorRequest",
    "FormulaRepair",
    "FormulaSuggestion",
    "RepairScope",
]
