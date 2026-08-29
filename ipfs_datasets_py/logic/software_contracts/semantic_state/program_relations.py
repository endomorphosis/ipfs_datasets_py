"""Closed scoped program-relation claims, invalidation, and validation receipts.

This module owns the datasets ``ScopedProgramRelation@1`` lifecycle, disjoint
from identity envelopes, accelerator admission, kit persistence, and ANN
scores.  A CID identifies canonical bytes; it does not establish truth,
equivalence, proof, authorization, freshness, safe reuse, or completion.

Authority rules (normative):

* Exact equality, refinement, entailment, contradiction, compatibility, and
  equivalence families remain scoped.  Changing scope, assumptions, theory or
  policy, or environment yields a different claim.
* Neural similarity, nearest-neighbor, embedding, and score material is never
  a semantic relation kind and cannot be encoded as semantic truth.
* Contradictory admitted premises yield conflict or abstention.  They never
  grant ex-falso admission of an unrelated claim.
* Candidate/asserted/validated/proved/refuted/unknown/stale/superseded is a
  closed authority vocabulary.  Proof validity remains delegated to current
  proof authorities; a relation claim is not authorization or safe reuse.
* Canonical bytes / CIDv1 come only from ``software_contracts.content``.
  Records are recursively immutable, closed to unknown fields, and restricted
  to strict DAG-JSON types.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Final, Iterable, Mapping, Sequence
import json
import unicodedata

from ipfs_datasets_py.logic.ir_core.canonical import (
    CanonicalizationError,
    CollectionSchema,
    CollectionSemantics,
    canonical_json_bytes as ir_canonical_json_bytes,
)
from ipfs_datasets_py.logic.software_contracts.content import (
    StructuredIdentityError,
    canonical_dag_json_bytes,
    cid_for_structured,
    decode_and_recompute_structured,
    validate_cid,
    validate_structured_value,
)


# ---------------------------------------------------------------------------
# Schema / interface constants (normative)
# ---------------------------------------------------------------------------

SCOPED_PROGRAM_RELATION_INTERFACE: Final[str] = "ScopedProgramRelation@1"
RELATION_VALIDATION_RECEIPT_INTERFACE: Final[str] = "RelationValidationReceipt@1"

RELATION_SCOPE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.relation-scope@1"
)
SCOPED_PROGRAM_RELATION_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.scoped-program-relation@1"
)
RELATION_CLAIM_IDENTITY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.relation-claim-identity@1"
)
RELATION_INVALIDATION_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.relation-invalidation@1"
)
RELATION_VALIDATION_RECEIPT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.relation-validation-receipt@1"
)

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_COLLECTION_ITEMS: Final[int] = 100_000
MAX_SAFE_INTEGER: Final[int] = (1 << 53) - 1

ADMITTED_LANGUAGES: Final[tuple[str, ...]] = ("python",)
UNAVAILABLE_LANGUAGES: Final[tuple[str, ...]] = (
    "javascript",
    "typescript",
    "rust",
    "c",
    "cpp",
    "java",
    "shell",
)

COLLECTION_SEMANTICS_DECLARATION: Final[dict[str, str]] = {
    "/assumption_cids": CollectionSemantics.SET_LIKE.value,
    "/conflict_claim_cids": CollectionSemantics.SET_LIKE.value,
    "/evidence_cids": CollectionSemantics.SET_LIKE.value,
    "/invalidator_cids": CollectionSemantics.SET_LIKE.value,
    "/limitation_cids": CollectionSemantics.SET_LIKE.value,
    "/subject_cids": CollectionSemantics.SET_LIKE.value,
    "/unavailable_dimensions": CollectionSemantics.SET_LIKE.value,
}

FORBIDDEN_RELATION_KINDS: Final[frozenset[str]] = frozenset(
    {
        "analogical",
        "ann",
        "cosine",
        "embedding",
        "embedding_neighbor",
        "knn",
        "nearest",
        "nearest_neighbor",
        "neural",
        "neural_similarity",
        "score",
        "similar",
        "similarity",
        "vector_neighbor",
    }
)

FORBIDDEN_FIELD_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "access_token",
        "ann_score",
        "api_key",
        "authorization",
        "cosine",
        "credential",
        "distance",
        "embedding",
        "embedding_score",
        "embeddings",
        "knn",
        "model",
        "model_cid",
        "nearest",
        "password",
        "private_key",
        "rank",
        "score",
        "scores",
        "secret",
        "similarity",
        "tokenizer_cid",
        "vector",
        "vector_cid",
        "vectors",
        "wall_clock",
    }
)

AUTHORITATIVE_STATUSES: Final[frozenset[str]] = frozenset({"validated", "proved"})
NEGATIVE_STATUSES: Final[frozenset[str]] = frozenset(
    {"refuted", "stale", "superseded"}
)
EVIDENCE_REQUIRED_STATUSES: Final[frozenset[str]] = frozenset(
    {"validated", "proved", "refuted"}
)
INVALIDATOR_REQUIRED_STATUSES: Final[frozenset[str]] = frozenset(
    {"stale", "superseded"}
)

ALLOWED_STATUS_TRANSITIONS: Final[Mapping[str, frozenset[str]]] = {
    "candidate": frozenset(
        {"asserted", "unknown", "stale", "superseded", "refuted"}
    ),
    "asserted": frozenset(
        {"validated", "unknown", "stale", "superseded", "refuted"}
    ),
    "validated": frozenset(
        {"proved", "unknown", "stale", "superseded", "refuted"}
    ),
    "proved": frozenset({"stale", "superseded", "refuted"}),
    "unknown": frozenset(
        {"candidate", "asserted", "stale", "superseded", "refuted"}
    ),
    "stale": frozenset({"superseded", "refuted"}),
    "superseded": frozenset(),
    "refuted": frozenset(),
}


class ProgramRelationError(ValueError):
    """Raised when a scoped relation payload or lifecycle step is malformed."""


class ProgramLanguage(str, Enum):
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    RUST = "rust"
    C = "c"
    CPP = "cpp"
    JAVA = "java"
    SHELL = "shell"


class RelationKind(str, Enum):
    EQUALITY = "equality"
    REFINEMENT = "refinement"
    ENTAILMENT = "entailment"
    CONTRADICTION = "contradiction"
    COMPATIBILITY = "compatibility"
    ALPHA_EQUIVALENCE = "alpha_equivalence"
    STRUCTURAL_EQUIVALENCE = "structural_equivalence"
    LOGICAL_EQUIVALENCE = "logical_equivalence"
    BEHAVIORAL_EQUIVALENCE = "behavioral_equivalence"
    OBSERVATIONAL_EQUIVALENCE = "observational_equivalence"
    INTENT = "intent"
    TRANSITION_BEHAVIOR = "transition_behavior"


class RelationFamily(str, Enum):
    EQUALITY = "equality"
    REFINEMENT = "refinement"
    ENTAILMENT = "entailment"
    CONTRADICTION = "contradiction"
    COMPATIBILITY = "compatibility"
    EQUIVALENCE = "equivalence"
    INTENT = "intent"
    TRANSITION_BEHAVIOR = "transition_behavior"


class RelationAuthorityStatus(str, Enum):
    CANDIDATE = "candidate"
    ASSERTED = "asserted"
    VALIDATED = "validated"
    PROVED = "proved"
    REFUTED = "refuted"
    UNKNOWN = "unknown"
    STALE = "stale"
    SUPERSEDED = "superseded"


class RelationScopeKind(str, Enum):
    MODULE = "module"
    SYMBOL = "symbol"
    PROGRAM_GRAPH = "program_graph"
    SNAPSHOT = "snapshot"
    EXECUTION_STATE = "execution_state"
    TRACE = "trace"
    THEORY = "theory"
    WORLD = "world"


class RelationInvalidationKind(str, Enum):
    SCOPE_CHANGED = "scope_changed"
    ASSUMPTION_INVALIDATED = "assumption_invalidated"
    ENVIRONMENT_CHANGED = "environment_changed"
    EVIDENCE_REFUTED = "evidence_refuted"
    SUPERSEDED = "superseded"
    CONTRADICTION_CONFLICT = "contradiction_conflict"


class RelationValidationVerdict(str, Enum):
    ADMITTED = "admitted"
    CONFLICT = "conflict"
    ABSTAIN = "abstain"
    REFUTED = "refuted"
    STALE = "stale"
    SUPERSEDED = "superseded"
    UNKNOWN = "unknown"


class ContradictionDisposition(str, Enum):
    CONFLICT = "conflict"
    ABSTENTION = "abstention"
    NOT_APPLICABLE = "not_applicable"


RELATION_KIND_FAMILY: Final[Mapping[str, str]] = {
    RelationKind.EQUALITY.value: RelationFamily.EQUALITY.value,
    RelationKind.REFINEMENT.value: RelationFamily.REFINEMENT.value,
    RelationKind.ENTAILMENT.value: RelationFamily.ENTAILMENT.value,
    RelationKind.CONTRADICTION.value: RelationFamily.CONTRADICTION.value,
    RelationKind.COMPATIBILITY.value: RelationFamily.COMPATIBILITY.value,
    RelationKind.ALPHA_EQUIVALENCE.value: RelationFamily.EQUIVALENCE.value,
    RelationKind.STRUCTURAL_EQUIVALENCE.value: RelationFamily.EQUIVALENCE.value,
    RelationKind.LOGICAL_EQUIVALENCE.value: RelationFamily.EQUIVALENCE.value,
    RelationKind.BEHAVIORAL_EQUIVALENCE.value: RelationFamily.EQUIVALENCE.value,
    RelationKind.OBSERVATIONAL_EQUIVALENCE.value: RelationFamily.EQUIVALENCE.value,
    RelationKind.INTENT.value: RelationFamily.INTENT.value,
    RelationKind.TRANSITION_BEHAVIOR.value: RelationFamily.TRANSITION_BEHAVIOR.value,
}

SYMMETRIC_RELATION_KINDS: Final[frozenset[str]] = frozenset(
    {
        RelationKind.EQUALITY.value,
        RelationKind.CONTRADICTION.value,
        RelationKind.COMPATIBILITY.value,
        RelationKind.ALPHA_EQUIVALENCE.value,
        RelationKind.STRUCTURAL_EQUIVALENCE.value,
        RelationKind.LOGICAL_EQUIVALENCE.value,
        RelationKind.BEHAVIORAL_EQUIVALENCE.value,
        RelationKind.OBSERVATIONAL_EQUIVALENCE.value,
    }
)

POSITIVE_RELATION_FAMILIES: Final[frozenset[str]] = frozenset(
    {
        RelationFamily.EQUALITY.value,
        RelationFamily.REFINEMENT.value,
        RelationFamily.ENTAILMENT.value,
        RelationFamily.COMPATIBILITY.value,
        RelationFamily.EQUIVALENCE.value,
        RelationFamily.INTENT.value,
        RelationFamily.TRANSITION_BEHAVIOR.value,
    }
)

SCOPED_RELATION_FAMILIES: Final[frozenset[str]] = frozenset(
    {
        RelationFamily.EQUALITY.value,
        RelationFamily.REFINEMENT.value,
        RelationFamily.ENTAILMENT.value,
        RelationFamily.CONTRADICTION.value,
        RelationFamily.COMPATIBILITY.value,
        RelationFamily.EQUIVALENCE.value,
    }
)

IDENTITY_CLAIM_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema",
        "relation_kind",
        "left_cid",
        "right_cid",
        "scope_cid",
        "assumption_cids",
        "theory_or_policy_cid",
        "environment_binding_cid",
        "evidence_cids",
        "invalidator_cids",
        "authority_status",
        "relation_claim_cid",
    }
)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value):
        raise ProgramRelationError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise ProgramRelationError(f"{name} must be trimmed NFC text")
    if len(value) > MAX_TEXT_CHARS or any(not char.isprintable() for char in value):
        raise ProgramRelationError(f"{name} contains invalid text")
    return value


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    if isinstance(value, enum_type):
        return value.value
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise ProgramRelationError(f"{name} has unsupported value {value!r}") from exc


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise ProgramRelationError(f"{name} must be a valid CID") from exc


def _optional_cid(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _cid(value, name)


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise ProgramRelationError(f"{name} must be a boolean")
    return value


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise ProgramRelationError(f"{name} must be a mapping")
    extra = set(data) - fields
    missing = fields - set(data)
    if extra:
        raise ProgramRelationError(f"{name} rejects unknown fields {sorted(extra)}")
    if missing:
        raise ProgramRelationError(f"{name} missing fields {sorted(missing)}")
    forbidden = set(data) & FORBIDDEN_FIELD_MARKERS
    if forbidden:
        raise ProgramRelationError(
            f"{name} rejects non-semantic fields {sorted(forbidden)}"
        )
    return dict(data)


def _unique_sorted_texts(values: Iterable[Any], name: str) -> tuple[str, ...]:
    items = [_text(value, name) for value in values]
    if len(items) > MAX_COLLECTION_ITEMS:
        raise ProgramRelationError(f"{name} exceeds its item bound")
    ordered = tuple(sorted(items))
    if len(ordered) != len(set(ordered)):
        raise ProgramRelationError(f"{name} must not contain duplicates")
    return ordered


def _unique_sorted_cids(values: Iterable[Any], name: str) -> tuple[str, ...]:
    items = [_cid(value, name) for value in values]
    if len(items) > MAX_COLLECTION_ITEMS:
        raise ProgramRelationError(f"{name} exceeds its item bound")
    ordered = tuple(sorted(items))
    if len(ordered) != len(set(ordered)):
        raise ProgramRelationError(f"{name} must not contain duplicates")
    return ordered


def _language(value: Any, name: str = "language") -> str:
    language = _enum(value, ProgramLanguage, name)
    if language not in ADMITTED_LANGUAGES:
        raise ProgramRelationError(
            f"{name} {language!r} is typed unavailable in this profile"
        )
    return language


def _relation_kind(value: Any, name: str = "relation_kind") -> str:
    if type(value) is str:
        marker = value.strip().lower().replace("-", "_").replace(" ", "_")
        if marker in FORBIDDEN_RELATION_KINDS:
            raise ProgramRelationError(
                "similarity/nearest-neighbor is not a semantic relation kind"
            )
    return _enum(value, RelationKind, name)


def _apply_collection_semantics(
    value: Any, *, path: tuple[str, ...], schema: CollectionSchema
) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _apply_collection_semantics(item, path=path + (key,), schema=schema)
            for key, item in value.items()
        }
    if isinstance(value, list):
        semantics = schema.semantics_for(path) or CollectionSemantics.ORDERED
        child_suffix = "*" if semantics is not CollectionSemantics.ORDERED else None
        prepared = [
            _apply_collection_semantics(
                item,
                path=path + ((child_suffix,) if child_suffix is not None else (str(index),)),
                schema=schema,
            )
            for index, item in enumerate(value)
        ]
        if semantics is CollectionSemantics.ORDERED:
            return prepared
        encoded = [(canonical_dag_json_bytes(item), item) for item in prepared]
        encoded.sort(key=lambda pair: pair[0])
        if semantics is CollectionSemantics.SET_LIKE:
            unique: list[Any] = []
            seen: set[bytes] = set()
            for blob, item in encoded:
                if blob in seen:
                    continue
                seen.add(blob)
                unique.append(item)
            return unique
        return [item for _, item in encoded]
    return value


def canonicalize_relation_value(value: Any) -> Any:
    """NFC-normalize, apply declared collection semantics, and reject floats."""

    try:
        validate_structured_value(value)
    except (StructuredIdentityError, TypeError, ValueError) as exc:
        raise ProgramRelationError("relation value must be strict DAG-JSON") from exc

    def normalize(item: Any) -> Any:
        if type(item) is str:
            return unicodedata.normalize("NFC", item)
        if isinstance(item, Mapping):
            return {normalize(key): normalize(child) for key, child in item.items()}
        if isinstance(item, list):
            return [normalize(child) for child in item]
        return item

    prepared = normalize(value)
    schema = CollectionSchema(COLLECTION_SEMANTICS_DECLARATION, require_declared=False)
    canonical = _apply_collection_semantics(prepared, path=(), schema=schema)
    try:
        validate_structured_value(canonical)
    except (StructuredIdentityError, TypeError, ValueError) as exc:
        raise ProgramRelationError(
            "canonical relation value must be strict DAG-JSON"
        ) from exc
    content_bytes = canonical_dag_json_bytes(canonical)
    try:
        ir_bytes = ir_canonical_json_bytes(
            canonical,
            collection_schema=CollectionSchema(None, require_declared=False),
        )
    except CanonicalizationError as exc:
        raise ProgramRelationError(
            "ir_core rejected the canonical relation value"
        ) from exc
    if ir_bytes != content_bytes:
        raise ProgramRelationError(
            "ir_core canonical JSON diverged from software-contract DAG-JSON"
        )
    return canonical


def relation_cid_for(payload: Mapping[str, Any]) -> str:
    """Return the structured CID of one canonical relation payload."""

    return cid_for_structured(canonicalize_relation_value(payload))


def canonical_relation_bytes(payload: Mapping[str, Any]) -> bytes:
    """Return canonical DAG-JSON bytes of one relation payload."""

    return canonical_dag_json_bytes(canonicalize_relation_value(payload))


def _verify_claimed(name: str, claimed: Any, payload: Mapping[str, Any]) -> str:
    canonical = canonicalize_relation_value(payload)
    try:
        return decode_and_recompute_structured(claimed, canonical)
    except Exception as exc:
        raise ProgramRelationError(f"{name} cid does not verify") from exc


def _verify_identity_claimed(
    name: str, claimed: Any, payload: Mapping[str, Any]
) -> str:
    """Rehash an identity envelope with the landed identity canonicalizer."""

    try:
        from ipfs_datasets_py.logic.software_contracts.semantic_state.program_identity import (
            canonicalize_identity_value,
        )
    except ImportError:
        return _verify_claimed(name, claimed, payload)
    try:
        canonical = canonicalize_identity_value(payload)
        return decode_and_recompute_structured(claimed, canonical)
    except ProgramRelationError:
        raise
    except Exception as exc:
        raise ProgramRelationError(f"{name} cid does not verify") from exc


def _reject_nonfinite_constant(token: str) -> None:
    raise ProgramRelationError(f"nonfinite JSON number {token!r} is rejected")


def _parse_int(token: str) -> int:
    try:
        value = int(token, 10)
    except ValueError as exc:
        raise ProgramRelationError(f"JSON number {token!r} is not an integer") from exc
    if value < -MAX_SAFE_INTEGER or value > MAX_SAFE_INTEGER:
        raise ProgramRelationError("integer is outside the safe JSON range")
    return value


def _parse_float(token: str) -> None:
    raise ProgramRelationError(
        f"JSON number {token!r} is not a finite integer; floats are rejected"
    )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProgramRelationError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def loads_relation_json(text: str | bytes) -> Any:
    """Decode JSON text, rejecting duplicate keys, NaN, and floats."""

    if type(text) is bytes:
        try:
            text = text.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProgramRelationError("relation JSON must be UTF-8") from exc
    if type(text) is not str:
        raise ProgramRelationError("relation JSON must be text or UTF-8 bytes")
    try:
        return json.loads(
            text,
            parse_int=_parse_int,
            parse_float=_parse_float,
            parse_constant=_reject_nonfinite_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except ProgramRelationError:
        raise
    except json.JSONDecodeError as exc:
        raise ProgramRelationError("relation JSON is not well-formed") from exc


def relation_family_for(kind: RelationKind | str) -> str:
    """Return the closed family of one admitted relation kind."""

    resolved = _relation_kind(kind)
    return RELATION_KIND_FAMILY[resolved]


def is_symmetric_relation(kind: RelationKind | str) -> bool:
    return _relation_kind(kind) in SYMMETRIC_RELATION_KINDS


def is_authoritative_status(status: RelationAuthorityStatus | str) -> bool:
    return _enum(status, RelationAuthorityStatus, "authority_status") in AUTHORITATIVE_STATUSES


def _pair_key(left_cid: str, right_cid: str, *, symmetric: bool) -> tuple[str, str]:
    if symmetric:
        first, second = sorted((left_cid, right_cid))
        return first, second
    return left_cid, right_cid


def _subject_key(
    kind: str, left_cid: str, right_cid: str, scope_cid: str
) -> tuple[str, str, str, str]:
    pair = _pair_key(left_cid, right_cid, symmetric=kind in SYMMETRIC_RELATION_KINDS)
    return kind, pair[0], pair[1], scope_cid


def _unordered_subject(left_cid: str, right_cid: str, scope_cid: str) -> tuple[str, str, str]:
    first, second = sorted((left_cid, right_cid))
    return first, second, scope_cid


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RelationScope:
    """Exact scope binding for a relation claim; unscoped relations are rejected."""

    scope_kind: RelationScopeKind | str
    language: ProgramLanguage | str
    subject_cids: Sequence[str]
    theory_or_policy_cid: str
    environment_binding_cid: str
    assumption_cids: Sequence[str] = ()
    unavailable_dimensions: Sequence[str] = ()

    SCHEMA: ClassVar[str] = RELATION_SCOPE_SCHEMA
    CID_FIELD: ClassVar[str] = "scope_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "scope_kind",
            "language",
            "subject_cids",
            "assumption_cids",
            "theory_or_policy_cid",
            "environment_binding_cid",
            "unavailable_dimensions",
            "scope_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "scope_kind", _enum(self.scope_kind, RelationScopeKind, "scope_kind")
        )
        object.__setattr__(self, "language", _language(self.language))
        object.__setattr__(
            self, "subject_cids", _unique_sorted_cids(self.subject_cids, "subject_cid")
        )
        if not self.subject_cids:
            raise ProgramRelationError("scope subject_cids must not be empty")
        object.__setattr__(
            self,
            "assumption_cids",
            _unique_sorted_cids(self.assumption_cids, "assumption_cid"),
        )
        object.__setattr__(
            self,
            "theory_or_policy_cid",
            _cid(self.theory_or_policy_cid, "theory_or_policy_cid"),
        )
        object.__setattr__(
            self,
            "environment_binding_cid",
            _cid(self.environment_binding_cid, "environment_binding_cid"),
        )
        object.__setattr__(
            self,
            "unavailable_dimensions",
            _unique_sorted_texts(
                self.unavailable_dimensions, "unavailable_dimension"
            ),
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "scope_kind": self.scope_kind,
            "language": self.language,
            "subject_cids": list(self.subject_cids),
            "assumption_cids": list(self.assumption_cids),
            "theory_or_policy_cid": self.theory_or_policy_cid,
            "environment_binding_cid": self.environment_binding_cid,
            "unavailable_dimensions": list(self.unavailable_dimensions),
        }

    @property
    def scope_cid(self) -> str:
        return relation_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_relation_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["scope_cid"] = self.scope_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RelationScope":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("scope_cid")
        if payload.pop("schema") != cls.SCHEMA:
            raise ProgramRelationError("unsupported RelationScope schema version")
        result = cls(**payload)
        _verify_claimed(cls.__name__, claimed, result.identity_payload())
        return result


@dataclass(frozen=True, slots=True)
class ProgramRelationClaim:
    """Scoped relation claim with assumptions, evidence, invalidators, and authority."""

    relation_kind: RelationKind | str
    left_cid: str
    right_cid: str
    scope_cid: str
    theory_or_policy_cid: str
    environment_binding_cid: str
    authority_status: RelationAuthorityStatus | str
    assumption_cids: Sequence[str] = ()
    evidence_cids: Sequence[str] = ()
    invalidator_cids: Sequence[str] = ()
    superseded_by_cid: str | None = None

    SCHEMA: ClassVar[str] = SCOPED_PROGRAM_RELATION_SCHEMA
    INTERFACE: ClassVar[str] = SCOPED_PROGRAM_RELATION_INTERFACE
    CID_FIELD: ClassVar[str] = "relation_claim_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "relation_kind",
            "left_cid",
            "right_cid",
            "scope_cid",
            "assumption_cids",
            "theory_or_policy_cid",
            "environment_binding_cid",
            "evidence_cids",
            "invalidator_cids",
            "authority_status",
            "superseded_by_cid",
            "relation_claim_cid",
        }
    )

    def __post_init__(self) -> None:
        kind = _relation_kind(self.relation_kind)
        status = _enum(self.authority_status, RelationAuthorityStatus, "authority_status")
        object.__setattr__(self, "relation_kind", kind)
        object.__setattr__(self, "left_cid", _cid(self.left_cid, "left_cid"))
        object.__setattr__(self, "right_cid", _cid(self.right_cid, "right_cid"))
        object.__setattr__(self, "scope_cid", _cid(self.scope_cid, "scope_cid"))
        object.__setattr__(
            self,
            "theory_or_policy_cid",
            _cid(self.theory_or_policy_cid, "theory_or_policy_cid"),
        )
        object.__setattr__(
            self,
            "environment_binding_cid",
            _cid(self.environment_binding_cid, "environment_binding_cid"),
        )
        object.__setattr__(self, "authority_status", status)
        object.__setattr__(
            self,
            "assumption_cids",
            _unique_sorted_cids(self.assumption_cids, "assumption_cid"),
        )
        object.__setattr__(
            self, "evidence_cids", _unique_sorted_cids(self.evidence_cids, "evidence_cid")
        )
        object.__setattr__(
            self,
            "invalidator_cids",
            _unique_sorted_cids(self.invalidator_cids, "invalidator_cid"),
        )
        object.__setattr__(
            self,
            "superseded_by_cid",
            _optional_cid(self.superseded_by_cid, "superseded_by_cid"),
        )
        if not self.scope_cid:
            raise ProgramRelationError("relation claims must remain scoped")
        if status in EVIDENCE_REQUIRED_STATUSES and not self.evidence_cids:
            raise ProgramRelationError(
                f"{status} relation claims require evidence_cids"
            )
        if status in INVALIDATOR_REQUIRED_STATUSES and not self.invalidator_cids:
            raise ProgramRelationError(
                f"{status} relation claims require invalidator_cids"
            )
        if status == RelationAuthorityStatus.SUPERSEDED.value and self.superseded_by_cid is None:
            raise ProgramRelationError("superseded claims require superseded_by_cid")
        if status != RelationAuthorityStatus.SUPERSEDED.value and self.superseded_by_cid is not None:
            raise ProgramRelationError(
                "superseded_by_cid is only admitted on superseded claims"
            )
        if self.invalidator_cids and status in AUTHORITATIVE_STATUSES:
            raise ProgramRelationError(
                "validated/proved claims cannot carry invalidators"
            )

    @property
    def relation_family(self) -> str:
        return RELATION_KIND_FAMILY[str(self.relation_kind)]

    @property
    def is_symmetric(self) -> bool:
        return str(self.relation_kind) in SYMMETRIC_RELATION_KINDS

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "relation_kind": self.relation_kind,
            "left_cid": self.left_cid,
            "right_cid": self.right_cid,
            "scope_cid": self.scope_cid,
            "assumption_cids": list(self.assumption_cids),
            "theory_or_policy_cid": self.theory_or_policy_cid,
            "environment_binding_cid": self.environment_binding_cid,
            "evidence_cids": list(self.evidence_cids),
            "invalidator_cids": list(self.invalidator_cids),
            "authority_status": self.authority_status,
            "superseded_by_cid": self.superseded_by_cid,
        }

    @property
    def relation_claim_cid(self) -> str:
        return relation_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_relation_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["relation_claim_cid"] = self.relation_claim_cid
        return value

    def bind_scope(self, scope: RelationScope) -> "ProgramRelationClaim":
        """Fail closed unless this claim is exactly bound to ``scope``."""

        if not isinstance(scope, RelationScope):
            raise ProgramRelationError("scope must be a RelationScope")
        extra_assumptions = set(self.assumption_cids) - set(scope.assumption_cids)
        if extra_assumptions:
            raise ProgramRelationError(
                "claim assumptions must be within the bound scope"
            )
        if (
            self.scope_cid != scope.scope_cid
            or self.theory_or_policy_cid != scope.theory_or_policy_cid
            or self.environment_binding_cid != scope.environment_binding_cid
        ):
            raise ProgramRelationError(
                "claim is not bound to the supplied relation scope"
            )
        return self

    def replace(self, **overrides: Any) -> "ProgramRelationClaim":
        payload = {
            "relation_kind": self.relation_kind,
            "left_cid": self.left_cid,
            "right_cid": self.right_cid,
            "scope_cid": self.scope_cid,
            "theory_or_policy_cid": self.theory_or_policy_cid,
            "environment_binding_cid": self.environment_binding_cid,
            "authority_status": self.authority_status,
            "assumption_cids": self.assumption_cids,
            "evidence_cids": self.evidence_cids,
            "invalidator_cids": self.invalidator_cids,
            "superseded_by_cid": self.superseded_by_cid,
        }
        payload.update(overrides)
        return ProgramRelationClaim(**payload)

    @classmethod
    def from_scope(
        cls,
        scope: RelationScope,
        *,
        relation_kind: RelationKind | str,
        left_cid: str,
        right_cid: str,
        authority_status: RelationAuthorityStatus | str = RelationAuthorityStatus.CANDIDATE,
        assumption_cids: Sequence[str] | None = None,
        evidence_cids: Sequence[str] = (),
        invalidator_cids: Sequence[str] = (),
        superseded_by_cid: str | None = None,
    ) -> "ProgramRelationClaim":
        if not isinstance(scope, RelationScope):
            raise ProgramRelationError("scope must be a RelationScope")
        assumptions = (
            scope.assumption_cids if assumption_cids is None else assumption_cids
        )
        claim = cls(
            relation_kind=relation_kind,
            left_cid=left_cid,
            right_cid=right_cid,
            scope_cid=scope.scope_cid,
            theory_or_policy_cid=scope.theory_or_policy_cid,
            environment_binding_cid=scope.environment_binding_cid,
            authority_status=authority_status,
            assumption_cids=assumptions,
            evidence_cids=evidence_cids,
            invalidator_cids=invalidator_cids,
            superseded_by_cid=superseded_by_cid,
        )
        return claim.bind_scope(scope)

    def to_identity_record(self) -> dict[str, Any]:
        """Project the landed identity envelope; lifecycle CID remains distinct."""

        payload = {
            "schema": RELATION_CLAIM_IDENTITY_SCHEMA,
            "relation_kind": self.relation_kind,
            "left_cid": self.left_cid,
            "right_cid": self.right_cid,
            "scope_cid": self.scope_cid,
            "assumption_cids": list(self.assumption_cids),
            "theory_or_policy_cid": self.theory_or_policy_cid,
            "environment_binding_cid": self.environment_binding_cid,
            "evidence_cids": list(self.evidence_cids),
            "invalidator_cids": list(self.invalidator_cids),
            "authority_status": self.authority_status,
        }
        try:
            from ipfs_datasets_py.logic.software_contracts.semantic_state.program_identity import (
                identity_cid_for,
            )
        except ImportError:
            identity_cid_for = relation_cid_for
        encoded = dict(payload)
        encoded["relation_claim_cid"] = identity_cid_for(payload)
        return encoded

    @classmethod
    def from_identity_record(
        cls,
        data: Mapping[str, Any] | Any,
        *,
        superseded_by_cid: str | None = None,
    ) -> "ProgramRelationClaim":
        """Lift a SAWM-002 identity envelope into a scoped lifecycle claim."""

        if isinstance(data, ProgramRelationClaim):
            return data
        if not isinstance(data, Mapping):
            to_dict = getattr(data, "to_dict", None)
            if not callable(to_dict):
                raise ProgramRelationError("identity record must be a mapping")
            data = to_dict()
            if not isinstance(data, Mapping):
                raise ProgramRelationError(
                    "identity record to_dict must return a mapping"
                )
        schema = data.get("schema")
        if schema == cls.SCHEMA:
            return cls.from_dict(data)
        if schema != RELATION_CLAIM_IDENTITY_SCHEMA:
            raise ProgramRelationError(
                "unsupported relation identity schema version"
            )
        payload = _closed(data, IDENTITY_CLAIM_FIELDS, "RelationClaimIdentity")
        claimed = payload.pop("relation_claim_cid")
        payload.pop("schema")
        identity_payload = {
            "schema": RELATION_CLAIM_IDENTITY_SCHEMA,
            "relation_kind": payload["relation_kind"],
            "left_cid": payload["left_cid"],
            "right_cid": payload["right_cid"],
            "scope_cid": payload["scope_cid"],
            "assumption_cids": list(payload["assumption_cids"]),
            "theory_or_policy_cid": payload["theory_or_policy_cid"],
            "environment_binding_cid": payload["environment_binding_cid"],
            "evidence_cids": list(payload["evidence_cids"]),
            "invalidator_cids": list(payload["invalidator_cids"]),
            "authority_status": payload["authority_status"],
        }
        _verify_identity_claimed("RelationClaimIdentity", claimed, identity_payload)
        status = _enum(
            payload["authority_status"], RelationAuthorityStatus, "authority_status"
        )
        if status == RelationAuthorityStatus.SUPERSEDED.value and superseded_by_cid is None:
            raise ProgramRelationError(
                "identity superseded claims require superseded_by_cid"
            )
        if status != RelationAuthorityStatus.SUPERSEDED.value:
            superseded_by_cid = None
        return cls(**payload, superseded_by_cid=superseded_by_cid)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProgramRelationClaim":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("relation_claim_cid")
        if payload.pop("schema") != cls.SCHEMA:
            raise ProgramRelationError(
                "unsupported ProgramRelationClaim schema version"
            )
        result = cls(**payload)
        _verify_claimed(cls.__name__, claimed, result.identity_payload())
        return result


ScopedProgramRelation = ProgramRelationClaim


@dataclass(frozen=True, slots=True)
class RelationInvalidation:
    """Immutable record that a scoped claim became stale, superseded, or refuted."""

    relation_claim_cid: str
    invalidation_kind: RelationInvalidationKind | str
    resulting_status: RelationAuthorityStatus | str
    invalidator_cids: Sequence[str]
    successor_claim_cid: str | None = None

    SCHEMA: ClassVar[str] = RELATION_INVALIDATION_SCHEMA
    CID_FIELD: ClassVar[str] = "relation_invalidation_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "relation_claim_cid",
            "invalidation_kind",
            "resulting_status",
            "invalidator_cids",
            "successor_claim_cid",
            "relation_invalidation_cid",
        }
    )

    def __post_init__(self) -> None:
        kind = _enum(
            self.invalidation_kind, RelationInvalidationKind, "invalidation_kind"
        )
        status = _enum(self.resulting_status, RelationAuthorityStatus, "resulting_status")
        object.__setattr__(self, "invalidation_kind", kind)
        object.__setattr__(self, "resulting_status", status)
        object.__setattr__(
            self,
            "relation_claim_cid",
            _cid(self.relation_claim_cid, "relation_claim_cid"),
        )
        object.__setattr__(
            self,
            "invalidator_cids",
            _unique_sorted_cids(self.invalidator_cids, "invalidator_cid"),
        )
        object.__setattr__(
            self,
            "successor_claim_cid",
            _optional_cid(self.successor_claim_cid, "successor_claim_cid"),
        )
        if not self.invalidator_cids:
            raise ProgramRelationError("invalidation requires invalidator_cids")
        if status not in NEGATIVE_STATUSES:
            raise ProgramRelationError(
                "invalidation resulting_status must be refuted, stale, or superseded"
            )
        if kind == RelationInvalidationKind.SUPERSEDED.value:
            if status != RelationAuthorityStatus.SUPERSEDED.value:
                raise ProgramRelationError(
                    "supersession invalidation must result in superseded"
                )
            if self.successor_claim_cid is None:
                raise ProgramRelationError(
                    "supersession invalidation requires successor_claim_cid"
                )
        if (
            kind == RelationInvalidationKind.EVIDENCE_REFUTED.value
            and status != RelationAuthorityStatus.REFUTED.value
        ):
            raise ProgramRelationError("evidence refutation must result in refuted")
        if self.successor_claim_cid == self.relation_claim_cid:
            raise ProgramRelationError("successor_claim_cid cannot equal the source claim")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "relation_claim_cid": self.relation_claim_cid,
            "invalidation_kind": self.invalidation_kind,
            "resulting_status": self.resulting_status,
            "invalidator_cids": list(self.invalidator_cids),
            "successor_claim_cid": self.successor_claim_cid,
        }

    @property
    def relation_invalidation_cid(self) -> str:
        return relation_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_relation_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["relation_invalidation_cid"] = self.relation_invalidation_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RelationInvalidation":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("relation_invalidation_cid")
        if payload.pop("schema") != cls.SCHEMA:
            raise ProgramRelationError(
                "unsupported RelationInvalidation schema version"
            )
        result = cls(**payload)
        _verify_claimed(cls.__name__, claimed, result.identity_payload())
        return result


@dataclass(frozen=True, slots=True)
class RelationValidationReceipt:
    """Independent validation outcome; never self-approves a relation claim."""

    relation_claim_cid: str
    verdict: RelationValidationVerdict | str
    authority_status: RelationAuthorityStatus | str
    contradiction_disposition: ContradictionDisposition | str
    conflict_claim_cids: Sequence[str] = ()
    evidence_cids: Sequence[str] = ()
    limitation_cids: Sequence[str] = ()
    similarity_authoritative: bool = False
    ex_falso_admission: bool = False

    SCHEMA: ClassVar[str] = RELATION_VALIDATION_RECEIPT_SCHEMA
    INTERFACE: ClassVar[str] = RELATION_VALIDATION_RECEIPT_INTERFACE
    CID_FIELD: ClassVar[str] = "relation_validation_receipt_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "relation_claim_cid",
            "verdict",
            "authority_status",
            "contradiction_disposition",
            "conflict_claim_cids",
            "evidence_cids",
            "limitation_cids",
            "similarity_authoritative",
            "ex_falso_admission",
            "relation_validation_receipt_cid",
        }
    )

    def __post_init__(self) -> None:
        verdict = _enum(self.verdict, RelationValidationVerdict, "verdict")
        status = _enum(self.authority_status, RelationAuthorityStatus, "authority_status")
        disposition = _enum(
            self.contradiction_disposition,
            ContradictionDisposition,
            "contradiction_disposition",
        )
        object.__setattr__(self, "verdict", verdict)
        object.__setattr__(self, "authority_status", status)
        object.__setattr__(self, "contradiction_disposition", disposition)
        object.__setattr__(
            self,
            "relation_claim_cid",
            _cid(self.relation_claim_cid, "relation_claim_cid"),
        )
        object.__setattr__(
            self,
            "conflict_claim_cids",
            _unique_sorted_cids(self.conflict_claim_cids, "conflict_claim_cid"),
        )
        object.__setattr__(
            self, "evidence_cids", _unique_sorted_cids(self.evidence_cids, "evidence_cid")
        )
        object.__setattr__(
            self,
            "limitation_cids",
            _unique_sorted_cids(self.limitation_cids, "limitation_cid"),
        )
        object.__setattr__(
            self,
            "similarity_authoritative",
            _bool(self.similarity_authoritative, "similarity_authoritative"),
        )
        object.__setattr__(
            self, "ex_falso_admission", _bool(self.ex_falso_admission, "ex_falso_admission")
        )
        if self.similarity_authoritative:
            raise ProgramRelationError(
                "neural similarity is never an authoritative relation"
            )
        if self.ex_falso_admission:
            raise ProgramRelationError(
                "contradictions cannot grant ex falso admission"
            )
        if verdict == RelationValidationVerdict.ADMITTED.value:
            if status not in AUTHORITATIVE_STATUSES:
                raise ProgramRelationError(
                    "admitted receipts require validated or proved authority"
                )
            if disposition != ContradictionDisposition.NOT_APPLICABLE.value:
                raise ProgramRelationError(
                    "admitted receipts cannot carry a contradiction disposition"
                )
            if self.conflict_claim_cids:
                raise ProgramRelationError("admitted receipts cannot list conflicts")
        if verdict == RelationValidationVerdict.CONFLICT.value:
            if not self.conflict_claim_cids:
                raise ProgramRelationError("conflict receipts require conflict_claim_cids")
            if disposition not in {
                ContradictionDisposition.CONFLICT.value,
                ContradictionDisposition.ABSTENTION.value,
            }:
                raise ProgramRelationError(
                    "conflict receipts must record conflict or abstention"
                )
        if verdict == RelationValidationVerdict.ABSTAIN.value:
            if disposition != ContradictionDisposition.ABSTENTION.value:
                raise ProgramRelationError(
                    "abstention receipts must record contradiction abstention"
                )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "relation_claim_cid": self.relation_claim_cid,
            "verdict": self.verdict,
            "authority_status": self.authority_status,
            "contradiction_disposition": self.contradiction_disposition,
            "conflict_claim_cids": list(self.conflict_claim_cids),
            "evidence_cids": list(self.evidence_cids),
            "limitation_cids": list(self.limitation_cids),
            "similarity_authoritative": self.similarity_authoritative,
            "ex_falso_admission": self.ex_falso_admission,
        }

    @property
    def relation_validation_receipt_cid(self) -> str:
        return relation_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_relation_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["relation_validation_receipt_cid"] = self.relation_validation_receipt_cid
        return value

    @property
    def may_influence_planning(self) -> bool:
        return (
            self.verdict == RelationValidationVerdict.ADMITTED.value
            and self.authority_status in AUTHORITATIVE_STATUSES
            and not self.similarity_authoritative
            and not self.ex_falso_admission
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RelationValidationReceipt":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("relation_validation_receipt_cid")
        if payload.pop("schema") != cls.SCHEMA:
            raise ProgramRelationError(
                "unsupported RelationValidationReceipt schema version"
            )
        result = cls(**payload)
        _verify_claimed(cls.__name__, claimed, result.identity_payload())
        return result


RELATION_RECORD_TYPES: Final[tuple[type, ...]] = (
    RelationScope,
    ProgramRelationClaim,
    RelationInvalidation,
    RelationValidationReceipt,
)

_SCHEMA_TO_CLASS: Final[dict[str, type]] = {
    cls.SCHEMA: cls for cls in RELATION_RECORD_TYPES
}


def decode_relation_record(data: Mapping[str, Any]) -> Any:
    """Dispatch one closed relation payload to its versioned record type."""

    if not isinstance(data, Mapping):
        raise ProgramRelationError("relation record must be a mapping")
    schema = data.get("schema")
    record_type = _SCHEMA_TO_CLASS.get(schema) if type(schema) is str else None
    if record_type is None:
        raise ProgramRelationError(f"unsupported relation schema {schema!r}")
    return record_type.from_dict(data)


def load_payload_schema() -> dict[str, Any]:
    """Load the packaged JSON Schema for program-relation payloads."""

    from pathlib import Path

    path = (
        Path(__file__).resolve().parent / "schemas" / "program-relation.payload.schema.json"
    )
    return loads_relation_json(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def promote_relation(
    claim: ProgramRelationClaim,
    target_status: RelationAuthorityStatus | str,
    *,
    evidence_cids: Sequence[str] | None = None,
    invalidator_cids: Sequence[str] | None = None,
    superseded_by_cid: str | None = None,
) -> ProgramRelationClaim:
    """Return a successor claim after a closed authority-status transition."""

    if not isinstance(claim, ProgramRelationClaim):
        raise ProgramRelationError("claim must be a ProgramRelationClaim")
    target = _enum(target_status, RelationAuthorityStatus, "target_status")
    current = str(claim.authority_status)
    allowed = ALLOWED_STATUS_TRANSITIONS[current]
    if target not in allowed:
        raise ProgramRelationError(
            f"cannot promote {current} relation to {target}"
        )
    evidence = claim.evidence_cids if evidence_cids is None else evidence_cids
    invalidators = (
        claim.invalidator_cids if invalidator_cids is None else invalidator_cids
    )
    successor = superseded_by_cid
    if target != RelationAuthorityStatus.SUPERSEDED.value:
        successor = None
    elif successor is None:
        raise ProgramRelationError("supersession requires superseded_by_cid")
    return claim.replace(
        authority_status=target,
        evidence_cids=evidence,
        invalidator_cids=invalidators,
        superseded_by_cid=successor,
    )


def _successor_status_for(kind: str) -> str:
    if kind == RelationInvalidationKind.EVIDENCE_REFUTED.value:
        return RelationAuthorityStatus.REFUTED.value
    if kind == RelationInvalidationKind.SUPERSEDED.value:
        return RelationAuthorityStatus.SUPERSEDED.value
    if kind == RelationInvalidationKind.CONTRADICTION_CONFLICT.value:
        return RelationAuthorityStatus.STALE.value
    return RelationAuthorityStatus.STALE.value


def invalidate_relation(
    claim: ProgramRelationClaim,
    invalidation_kind: RelationInvalidationKind | str,
    invalidator_cids: Sequence[str],
    *,
    successor_claim_cid: str | None = None,
    evidence_cids: Sequence[str] | None = None,
) -> tuple[ProgramRelationClaim, RelationInvalidation]:
    """Emit a successor claim and an invalidation record.  History is preserved."""

    if not isinstance(claim, ProgramRelationClaim):
        raise ProgramRelationError("claim must be a ProgramRelationClaim")
    kind = _enum(invalidation_kind, RelationInvalidationKind, "invalidation_kind")
    resulting = _successor_status_for(kind)
    merged_invalidators = tuple(
        sorted(set(claim.invalidator_cids) | set(_unique_sorted_cids(invalidator_cids, "invalidator_cid")))
    )
    evidence = claim.evidence_cids if evidence_cids is None else evidence_cids
    if kind == RelationInvalidationKind.EVIDENCE_REFUTED.value and not evidence:
        evidence = merged_invalidators
    successor_override = successor_claim_cid
    if kind == RelationInvalidationKind.SUPERSEDED.value and successor_override is None:
        raise ProgramRelationError("supersession requires successor_claim_cid")
    successor = promote_relation(
        claim,
        resulting,
        evidence_cids=evidence,
        invalidator_cids=merged_invalidators,
        superseded_by_cid=successor_override,
    )
    record = RelationInvalidation(
        relation_claim_cid=claim.relation_claim_cid,
        invalidation_kind=kind,
        resulting_status=resulting,
        invalidator_cids=merged_invalidators,
        successor_claim_cid=successor.relation_claim_cid
        if kind != RelationInvalidationKind.SUPERSEDED.value
        else successor_override,
    )
    return successor, record


def invalidate_by_scope(
    claim: ProgramRelationClaim,
    current_scope: RelationScope,
) -> tuple[ProgramRelationClaim, RelationInvalidation] | None:
    if not isinstance(claim, ProgramRelationClaim):
        raise ProgramRelationError("claim must be a ProgramRelationClaim")
    if not isinstance(current_scope, RelationScope):
        raise ProgramRelationError("current_scope must be a RelationScope")
    if claim.scope_cid == current_scope.scope_cid:
        return None
    return invalidate_relation(
        claim,
        RelationInvalidationKind.SCOPE_CHANGED,
        (current_scope.scope_cid,),
    )


def invalidate_by_assumption(
    claim: ProgramRelationClaim,
    invalidated_assumption_cids: Sequence[str],
) -> tuple[ProgramRelationClaim, RelationInvalidation] | None:
    hit = set(claim.assumption_cids) & set(
        _unique_sorted_cids(invalidated_assumption_cids, "assumption_cid")
    )
    if not hit:
        return None
    return invalidate_relation(
        claim,
        RelationInvalidationKind.ASSUMPTION_INVALIDATED,
        tuple(sorted(hit)),
    )


def invalidate_by_environment(
    claim: ProgramRelationClaim,
    current_environment_binding_cid: str,
) -> tuple[ProgramRelationClaim, RelationInvalidation] | None:
    current = _cid(current_environment_binding_cid, "current_environment_binding_cid")
    if claim.environment_binding_cid == current:
        return None
    return invalidate_relation(
        claim,
        RelationInvalidationKind.ENVIRONMENT_CHANGED,
        (current,),
    )


def claims_conflict(left: ProgramRelationClaim, right: ProgramRelationClaim) -> bool:
    """Return True when two scoped claims cannot be jointly admitted.

    Only admitted (validated/proved) contradictory premises collide. A
    candidate, unknown, stale, or superseded contradiction cannot grant ex
    falso admission and also cannot veto an independently admitted positive
    claim. Proved and refuted records of the same scoped kind still conflict.
    """

    if not isinstance(left, ProgramRelationClaim) or not isinstance(
        right, ProgramRelationClaim
    ):
        raise ProgramRelationError("claims must be ProgramRelationClaim records")
    if left.relation_claim_cid == right.relation_claim_cid:
        return False
    if left.scope_cid != right.scope_cid:
        return False
    if (
        left.theory_or_policy_cid != right.theory_or_policy_cid
        or left.environment_binding_cid != right.environment_binding_cid
    ):
        return False
    unordered_left = _unordered_subject(left.left_cid, left.right_cid, left.scope_cid)
    unordered_right = _unordered_subject(right.left_cid, right.right_cid, right.scope_cid)
    if unordered_left != unordered_right:
        return False
    left_family = left.relation_family
    right_family = right.relation_family
    left_status = str(left.authority_status)
    right_status = str(right.authority_status)
    if (
        left_family == RelationFamily.CONTRADICTION.value
        and right_family in POSITIVE_RELATION_FAMILIES
    ) or (
        right_family == RelationFamily.CONTRADICTION.value
        and left_family in POSITIVE_RELATION_FAMILIES
    ):
        return (
            left_status in AUTHORITATIVE_STATUSES
            and right_status in AUTHORITATIVE_STATUSES
        )
    if left.relation_kind == right.relation_kind:
        statuses = {left_status, right_status}
        if RelationAuthorityStatus.REFUTED.value in statuses and statuses & AUTHORITATIVE_STATUSES:
            return True
    return False


def detect_conflicts(
    claims: Sequence[ProgramRelationClaim],
) -> tuple[tuple[str, str], ...]:
    """Return sorted unique conflicting claim-CID pairs."""

    items = tuple(claims)
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for index, left in enumerate(items):
        if not isinstance(left, ProgramRelationClaim):
            raise ProgramRelationError("claims must be ProgramRelationClaim records")
        for right in items[index + 1 :]:
            if not claims_conflict(left, right):
                continue
            pair = tuple(sorted((left.relation_claim_cid, right.relation_claim_cid)))
            typed = (pair[0], pair[1])
            if typed in seen:
                continue
            seen.add(typed)
            pairs.append(typed)
    return tuple(pairs)


def _freshness_failure(
    claim: ProgramRelationClaim,
    *,
    current_scope_cid: str | None,
    current_environment_binding_cid: str | None,
    invalidated_assumption_cids: Sequence[str],
) -> str | None:
    if current_scope_cid is not None and claim.scope_cid != _cid(
        current_scope_cid, "current_scope_cid"
    ):
        return RelationValidationVerdict.STALE.value
    if current_environment_binding_cid is not None and claim.environment_binding_cid != _cid(
        current_environment_binding_cid, "current_environment_binding_cid"
    ):
        return RelationValidationVerdict.STALE.value
    invalidated = set(_unique_sorted_cids(invalidated_assumption_cids, "assumption_cid"))
    if set(claim.assumption_cids) & invalidated:
        return RelationValidationVerdict.STALE.value
    return None


def validate_relation_claim(
    claim: ProgramRelationClaim,
    *,
    current_scope_cid: str | None = None,
    current_environment_binding_cid: str | None = None,
    invalidated_assumption_cids: Sequence[str] = (),
    peer_claims: Sequence[ProgramRelationClaim] = (),
) -> RelationValidationReceipt:
    """Independently assess one claim.  The claim cannot approve itself."""

    if not isinstance(claim, ProgramRelationClaim):
        raise ProgramRelationError("claim must be a ProgramRelationClaim")
    status = str(claim.authority_status)
    peers: list[ProgramRelationClaim] = []
    for peer in peer_claims:
        if not isinstance(peer, ProgramRelationClaim):
            raise ProgramRelationError("peer_claims must be ProgramRelationClaim records")
        peers.append(peer)
    conflicts = [
        peer.relation_claim_cid
        for peer in peers
        if claims_conflict(claim, peer)
    ]
    freshness = None
    if status not in NEGATIVE_STATUSES:
        freshness = _freshness_failure(
            claim,
            current_scope_cid=current_scope_cid,
            current_environment_binding_cid=current_environment_binding_cid,
            invalidated_assumption_cids=invalidated_assumption_cids,
        )
    if conflicts:
        return RelationValidationReceipt(
            relation_claim_cid=claim.relation_claim_cid,
            verdict=RelationValidationVerdict.CONFLICT,
            authority_status=status,
            contradiction_disposition=ContradictionDisposition.CONFLICT,
            conflict_claim_cids=conflicts,
            evidence_cids=claim.evidence_cids,
        )
    if freshness is not None:
        return RelationValidationReceipt(
            relation_claim_cid=claim.relation_claim_cid,
            verdict=freshness,
            authority_status=RelationAuthorityStatus.STALE,
            contradiction_disposition=ContradictionDisposition.NOT_APPLICABLE,
            evidence_cids=claim.evidence_cids,
            limitation_cids=claim.invalidator_cids,
        )
    if status == RelationAuthorityStatus.REFUTED.value:
        verdict = RelationValidationVerdict.REFUTED.value
    elif status == RelationAuthorityStatus.STALE.value:
        verdict = RelationValidationVerdict.STALE.value
    elif status == RelationAuthorityStatus.SUPERSEDED.value:
        verdict = RelationValidationVerdict.SUPERSEDED.value
    elif status in AUTHORITATIVE_STATUSES:
        verdict = RelationValidationVerdict.ADMITTED.value
    else:
        verdict = RelationValidationVerdict.UNKNOWN.value
    return RelationValidationReceipt(
        relation_claim_cid=claim.relation_claim_cid,
        verdict=verdict,
        authority_status=status,
        contradiction_disposition=ContradictionDisposition.NOT_APPLICABLE,
        evidence_cids=claim.evidence_cids,
        limitation_cids=claim.invalidator_cids,
    )


def validate_relation_set(
    claims: Sequence[ProgramRelationClaim],
    *,
    current_scope_cid: str | None = None,
    current_environment_binding_cid: str | None = None,
    invalidated_assumption_cids: Sequence[str] = (),
) -> tuple[RelationValidationReceipt, ...]:
    items = tuple(claims)
    return tuple(
        validate_relation_claim(
            claim,
            current_scope_cid=current_scope_cid,
            current_environment_binding_cid=current_environment_binding_cid,
            invalidated_assumption_cids=invalidated_assumption_cids,
            peer_claims=items,
        )
        for claim in items
    )


def attempt_ex_falso_admission(
    contradiction: ProgramRelationClaim,
    target: ProgramRelationClaim,
) -> RelationValidationReceipt:
    """Reject using a contradiction as a license to admit an unrelated claim."""

    if not isinstance(contradiction, ProgramRelationClaim) or not isinstance(
        target, ProgramRelationClaim
    ):
        raise ProgramRelationError("ex falso inputs must be ProgramRelationClaim records")
    if contradiction.relation_family != RelationFamily.CONTRADICTION.value:
        raise ProgramRelationError("ex falso attempt requires a contradiction claim")
    return RelationValidationReceipt(
        relation_claim_cid=target.relation_claim_cid,
        verdict=RelationValidationVerdict.ABSTAIN,
        authority_status=target.authority_status,
        contradiction_disposition=ContradictionDisposition.ABSTENTION,
        conflict_claim_cids=(contradiction.relation_claim_cid,),
        evidence_cids=target.evidence_cids,
        similarity_authoritative=False,
        ex_falso_admission=False,
    )


def may_influence_planning(
    claim: ProgramRelationClaim,
    receipt: RelationValidationReceipt,
) -> bool:
    """Proof-backed scoped relations may influence planning; similarity may not."""

    if not isinstance(claim, ProgramRelationClaim) or not isinstance(
        receipt, RelationValidationReceipt
    ):
        raise ProgramRelationError("planning admission requires claim and receipt")
    if receipt.relation_claim_cid != claim.relation_claim_cid:
        raise ProgramRelationError("receipt does not bind the supplied claim")
    if str(receipt.authority_status) != str(claim.authority_status):
        raise ProgramRelationError("receipt authority_status does not bind the claim")
    if claim.relation_kind in FORBIDDEN_RELATION_KINDS:
        return False
    if str(claim.authority_status) not in AUTHORITATIVE_STATUSES:
        return False
    if receipt.similarity_authoritative or receipt.ex_falso_admission:
        return False
    return receipt.may_influence_planning


__all__ = [
    "ADMITTED_LANGUAGES",
    "ALLOWED_STATUS_TRANSITIONS",
    "AUTHORITATIVE_STATUSES",
    "COLLECTION_SEMANTICS_DECLARATION",
    "FORBIDDEN_RELATION_KINDS",
    "IDENTITY_CLAIM_FIELDS",
    "POSITIVE_RELATION_FAMILIES",
    "RELATION_CLAIM_IDENTITY_SCHEMA",
    "RELATION_INVALIDATION_SCHEMA",
    "RELATION_KIND_FAMILY",
    "RELATION_SCOPE_SCHEMA",
    "RELATION_VALIDATION_RECEIPT_INTERFACE",
    "RELATION_VALIDATION_RECEIPT_SCHEMA",
    "SCOPED_PROGRAM_RELATION_INTERFACE",
    "SCOPED_PROGRAM_RELATION_SCHEMA",
    "SCOPED_RELATION_FAMILIES",
    "SYMMETRIC_RELATION_KINDS",
    "ContradictionDisposition",
    "ProgramLanguage",
    "ProgramRelationClaim",
    "ProgramRelationError",
    "RelationAuthorityStatus",
    "RelationFamily",
    "RelationInvalidation",
    "RelationInvalidationKind",
    "RelationKind",
    "RelationScope",
    "RelationScopeKind",
    "RelationValidationReceipt",
    "RelationValidationVerdict",
    "ScopedProgramRelation",
    "attempt_ex_falso_admission",
    "canonical_relation_bytes",
    "canonicalize_relation_value",
    "claims_conflict",
    "decode_relation_record",
    "detect_conflicts",
    "invalidate_by_assumption",
    "invalidate_by_environment",
    "invalidate_by_scope",
    "invalidate_relation",
    "is_authoritative_status",
    "is_symmetric_relation",
    "load_payload_schema",
    "loads_relation_json",
    "may_influence_planning",
    "promote_relation",
    "relation_cid_for",
    "relation_family_for",
    "validate_relation_claim",
    "validate_relation_set",
]
