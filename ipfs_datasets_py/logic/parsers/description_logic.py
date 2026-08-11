"""Description-logic and ontology profiles (``DescriptionLogicProfiles@1``).

Controlled concept, role, individual, inclusion, disjointness, cardinality,
and ontology-import identities for legal, UI, intent, and knowledge-graph
use cases.

**Open-world semantics are explicit.** Every profile declares
``world_assumption=OPEN_WORLD`` by default. Closed-world or negation-as-failure
readings are never inferred. Complete OWL remains declaration-only; this
module never silently approximates unsupported OWL constructs as FOL.

Owned constructs (profile-gated):

* atomic concepts / roles / individuals with stable identities
* top (``Thing`` / ⊤) and bottom (``Nothing`` / ⊥)
* concept constructors: ``and``, ``or``, ``not``, ``some``, ``only``
* qualified number restrictions: ``min``, ``max``, ``exactly`` (ALCQ)
* axioms: ``SubClassOf``, ``EquivalentClasses``, ``DisjointClasses``,
  ``ClassAssertion``, ``ObjectPropertyAssertion``
* ontology imports: ``Import(iri)``

Unsupported OWL constructs fail closed (no silent FOL approximation):

* property chains, inverse roles, nominals/oneOf, datatypes/data properties
* SWRL rules, keys/hasKey, universal role, role composition
* full OWL 2 DL / complete OWL beyond the declared DL profile

Evidence subset: description logic ontology concept role axiom legal ui kg
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.syntax_core.algebra import alpha_equivalent
from ipfs_datasets_py.logic.syntax_core.ast import (
    LogicNode,
    NodeKind,
    TypedExpression,
    mk_extension,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
    CSTNodeRole,
    DiagnosticSeverity,
    LogicCST,
    LogicCSTNode,
    LogicToken,
    ParseArtifact,
    ParseLimits,
    ParseMode,
    ParseRequest,
    ParseStatus,
    SourceDocument,
    SourceRange,
    SurfaceASTRef,
    SyntaxContractError,
    SyntaxDiagnostic,
    TokenKind,
)
from ipfs_datasets_py.logic.syntax_core.lexer import BoundedLexer
from ipfs_datasets_py.logic.syntax_core.signatures import (
    BOOL_SORT,
    LogicSignature,
    atomic_sort,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

DESCRIPTION_LOGIC_PROFILES_INTERFACE: Final = "DescriptionLogicProfiles@1"
DESCRIPTION_LOGIC_PROFILE_INTERFACE: Final = "DescriptionLogicProfile@1"
ONTOLOGY_PROFILE_INTERFACE: Final = "OntologyProfile@1"

DL_NOTATION_ID: Final = "canonical_description_logic"
DL_NOTATION_VERSION: Final = "1.0.0"
DL_FAMILY_ID: Final = "description_logic"
DL_MODULE_VERSION: Final = "1.0.0"

DL_PARSE_RESULT_SCHEMA: Final = "canonical-description-logic-parse-result/v1"
DL_PROFILE_SCHEMA: Final = "description-logic-profile/v1"
DL_ONTOLOGY_PROFILE_SCHEMA: Final = "ontology-profile/v1"
DL_IDENTITY_SCHEMA: Final = "description-logic.identity/v1"
DL_EVIDENCE_CONTRACT_SCHEMA: Final = "description-logic.evidence-contract/v1"
DL_SOURCE_MAP_SCHEMA: Final = "description-logic.source-map/v1"

# Extension payload schemas.
DL_CONCEPT_ATOMIC_SCHEMA: Final = "description_logic.concept.atomic/v1"
DL_CONCEPT_TOP_SCHEMA: Final = "description_logic.concept.top/v1"
DL_CONCEPT_BOTTOM_SCHEMA: Final = "description_logic.concept.bottom/v1"
DL_CONCEPT_AND_SCHEMA: Final = "description_logic.concept.and/v1"
DL_CONCEPT_OR_SCHEMA: Final = "description_logic.concept.or/v1"
DL_CONCEPT_NOT_SCHEMA: Final = "description_logic.concept.not/v1"
DL_CONCEPT_SOME_SCHEMA: Final = "description_logic.concept.some/v1"
DL_CONCEPT_ONLY_SCHEMA: Final = "description_logic.concept.only/v1"
DL_CONCEPT_MIN_SCHEMA: Final = "description_logic.concept.min/v1"
DL_CONCEPT_MAX_SCHEMA: Final = "description_logic.concept.max/v1"
DL_CONCEPT_EXACTLY_SCHEMA: Final = "description_logic.concept.exactly/v1"
DL_ROLE_ATOMIC_SCHEMA: Final = "description_logic.role.atomic/v1"
DL_INDIVIDUAL_SCHEMA: Final = "description_logic.individual/v1"
DL_AXIOM_SUBCLASS_SCHEMA: Final = "description_logic.axiom.subclass_of/v1"
DL_AXIOM_EQUIV_SCHEMA: Final = "description_logic.axiom.equivalent_classes/v1"
DL_AXIOM_DISJOINT_SCHEMA: Final = "description_logic.axiom.disjoint_classes/v1"
DL_AXIOM_CLASS_ASSERT_SCHEMA: Final = "description_logic.axiom.class_assertion/v1"
DL_AXIOM_ROLE_ASSERT_SCHEMA: Final = (
    "description_logic.axiom.object_property_assertion/v1"
)
DL_IMPORT_SCHEMA: Final = "description_logic.ontology.import/v1"
DL_ONTOLOGY_DOC_SCHEMA: Final = "description_logic.ontology.document/v1"

CONCEPT_SORT: Final = atomic_sort("Concept")
ROLE_SORT: Final = atomic_sort("Role")
INDIVIDUAL_DL_SORT: Final = atomic_sort("Individual")
ONTOLOGY_SORT: Final = atomic_sort("Ontology")

# Stable namespaced diagnostic codes.
CODE_UNEXPECTED_TOKEN: Final = "description_logic.unexpected_token"
CODE_TRAILING_INPUT: Final = "description_logic.trailing_input"
CODE_EMPTY_INPUT: Final = "description_logic.empty_input"
CODE_PARSE_DEPTH: Final = "description_logic.parse_depth_exceeded"
CODE_UNBALANCED: Final = "description_logic.unbalanced_delimiter"
CODE_LEXER_ERROR: Final = "description_logic.lexer_error"
CODE_UNKNOWN_CHARACTER: Final = "description_logic.unknown_character"
CODE_PROFILE_MISMATCH: Final = "description_logic.profile_mismatch"
CODE_ARITY_MISMATCH: Final = "description_logic.arity_mismatch"
CODE_UNSUPPORTED_OWL: Final = "description_logic.unsupported_owl_construct"
CODE_FOL_APPROXIMATION_REJECTED: Final = (
    "description_logic.fol_approximation_rejected"
)
CODE_OPEN_WORLD_VIOLATION: Final = "description_logic.open_world_violation"
CODE_INVALID_CARDINALITY: Final = "description_logic.invalid_cardinality"
CODE_INVALID_IDENTITY: Final = "description_logic.invalid_identity"
CODE_ROUND_TRIP: Final = "description_logic.round_trip_failed"
CODE_COMPLETE_OWL_REJECTED: Final = "description_logic.complete_owl_rejected"

_ALL_DL_CODES: Final[frozenset[str]] = frozenset(
    {
        CODE_UNEXPECTED_TOKEN,
        CODE_TRAILING_INPUT,
        CODE_EMPTY_INPUT,
        CODE_PARSE_DEPTH,
        CODE_UNBALANCED,
        CODE_LEXER_ERROR,
        CODE_UNKNOWN_CHARACTER,
        CODE_PROFILE_MISMATCH,
        CODE_ARITY_MISMATCH,
        CODE_UNSUPPORTED_OWL,
        CODE_FOL_APPROXIMATION_REJECTED,
        CODE_OPEN_WORLD_VIOLATION,
        CODE_INVALID_CARDINALITY,
        CODE_INVALID_IDENTITY,
        CODE_ROUND_TRIP,
        CODE_COMPLETE_OWL_REJECTED,
    }
)

# OWL / DL surface keywords that are intentionally unsupported.
_UNSUPPORTED_OWL_KEYWORDS: Final[frozenset[str]] = frozenset(
    {
        "inverseof",
        "inverse",
        "objectinverseof",
        "propertychain",
        "objectpropertychain",
        "oneof",
        "objectoneof",
        "hasvalue",
        "objecthasvalue",
        "hasself",
        "objecthasself",
        "dataproperty",
        "datatype",
        "datarange",
        "literal",
        "swrl",
        "rule",
        "haskey",
        "keys",
        "universalrole",
        "topobjectproperty",
        "bottomobjectproperty",
        "reflexive",
        "irreflexive",
        "asymmetric",
        "symmetric",
        "transitive",
        "functional",
        "inversefunctional",
        "sameas",
        "differentfrom",
        "alldifferent",
        "complementof",  # Manchester OWL full; we use not(...)
        "objectpropertychainaxiom",
        "subobjectpropertyof",
        "equivalentobjectproperties",
        "disjointobjectproperties",
        "objectpropertydomain",
        "objectpropertyrange",
        "datapropertydomain",
        "datapropertyrange",
        "subdatapropertyof",
        "equivalentdataproperties",
        "disjointdataproperties",
        "datapropertyassertion",
        "negativeobjectpropertyassertion",
        "negativedatapropertyassertion",
        "annotationassertion",
        "declare",
        "prefix",
        "ontology",  # full OWL Ontology(...) header
    }
)

_AXIOM_ATOMS: Final[frozenset[str]] = frozenset(
    {
        "subclassof",
        "equivalentclasses",
        "disjointclasses",
        "classassertion",
        "objectpropertyassertion",
        "import",
    }
)

_CONCEPT_CONSTRUCTORS: Final[frozenset[str]] = frozenset(
    {
        "and",
        "or",
        "not",
        "some",
        "only",
        "all",
        "min",
        "max",
        "exactly",
        "thing",
        "nothing",
    }
)

_DL_KEYWORDS: Final[tuple[str, ...]] = (
    "and",
    "or",
    "not",
    "some",
    "only",
    "all",
    "min",
    "max",
    "exactly",
    "thing",
    "nothing",
    "subclassof",
    "equivalentclasses",
    "disjointclasses",
    "classassertion",
    "objectpropertyassertion",
    "import",
    "true",
    "false",
    # Unsupported keywords registered so the lexer tags them as keywords
    # and the parser can reject them with CODE_UNSUPPORTED_OWL.
    "inverseof",
    "inverse",
    "objectinverseof",
    "propertychain",
    "objectpropertychain",
    "oneof",
    "objectoneof",
    "hasvalue",
    "objecthasvalue",
    "hasself",
    "objecthasself",
    "dataproperty",
    "datatype",
    "datarange",
    "swrl",
    "rule",
    "haskey",
    "keys",
    "universalrole",
    "topobjectproperty",
    "bottomobjectproperty",
    "reflexive",
    "irreflexive",
    "asymmetric",
    "symmetric",
    "transitive",
    "functional",
    "inversefunctional",
    "sameas",
    "differentfrom",
    "alldifferent",
    "subobjectpropertyof",
    "equivalentobjectproperties",
    "disjointobjectproperties",
    "objectpropertydomain",
    "objectpropertyrange",
    "datapropertydomain",
    "datapropertyrange",
    "subdatapropertyof",
    "equivalentdataproperties",
    "disjointdataproperties",
    "datapropertyassertion",
    "negativeobjectpropertyassertion",
    "negativedatapropertyassertion",
    "annotationassertion",
    "declare",
    "prefix",
    "ontology",
)


class PrintStyle:
    """Printer surface style."""

    ASCII = "ascii"
    UNICODE = "unicode"


class DLExpressivity(str, Enum):
    """Controlled description-logic expressivity tiers.

    Complete OWL is intentionally absent; only ALC / ALCQ / EL subsets
    are executable under this interface.
    """

    EL = "EL"
    ALC = "ALC"
    ALCQ = "ALCQ"


class WorldAssumption(str, Enum):
    """World-assumption semantics for ontology reasoning.

    Open-world is the only default. Closed-world is never silently applied.
    """

    OPEN_WORLD = "open_world"
    CLOSED_WORLD = "closed_world"


class DomainUseCase(str, Enum):
    """Domain use-case tags for ontology profiles."""

    LEGAL = "legal"
    UI = "ui"
    INTENT = "intent"
    KNOWLEDGE_GRAPH = "knowledge_graph"
    GENERIC = "generic"


class ConceptConstructor(str, Enum):
    """Concept constructor kinds admitted by controlled profiles."""

    ATOMIC = "atomic"
    TOP = "top"
    BOTTOM = "bottom"
    AND = "and"
    OR = "or"
    NOT = "not"
    SOME = "some"
    ONLY = "only"
    MIN = "min"
    MAX = "max"
    EXACTLY = "exactly"


class AxiomKind(str, Enum):
    """Supported axiom kinds."""

    SUBCLASS_OF = "subclass_of"
    EQUIVALENT_CLASSES = "equivalent_classes"
    DISJOINT_CLASSES = "disjoint_classes"
    CLASS_ASSERTION = "class_assertion"
    OBJECT_PROPERTY_ASSERTION = "object_property_assertion"
    IMPORT = "import"


class EvidenceSource(str, Enum):
    """Origin of DL / ontology evidence (closed set)."""

    NONE = "none"
    LOCAL_CLASSIFIER = "local_classifier"
    TABLEAU_REASONER = "tableau_reasoner"
    OWL_REASONER = "owl_reasoner"
    FOL_APPROXIMATION = "fol_approximation"
    DECLARATION = "declaration"


class EvidenceAuthority(str, Enum):
    """Authority conveyed by DL evidence.

    FOL approximation is never promoted to DL/OWL reasoning authority.
    """

    NONE = "none"
    ADVISORY = "advisory"
    BOUNDED = "bounded"
    CLASSIFICATION = "classification"
    ENTAILMENT = "entailment"


_SOURCE_AUTHORITY_CEILING: Final[Mapping[EvidenceSource, EvidenceAuthority]] = {
    EvidenceSource.NONE: EvidenceAuthority.NONE,
    EvidenceSource.DECLARATION: EvidenceAuthority.ADVISORY,
    EvidenceSource.LOCAL_CLASSIFIER: EvidenceAuthority.BOUNDED,
    EvidenceSource.TABLEAU_REASONER: EvidenceAuthority.ENTAILMENT,
    EvidenceSource.OWL_REASONER: EvidenceAuthority.ENTAILMENT,
    # FOL approximation is advisory only and never DL entailment authority.
    EvidenceSource.FOL_APPROXIMATION: EvidenceAuthority.ADVISORY,
}

_AUTHORITY_RANK: Final[Mapping[EvidenceAuthority, int]] = {
    EvidenceAuthority.NONE: 0,
    EvidenceAuthority.ADVISORY: 1,
    EvidenceAuthority.BOUNDED: 2,
    EvidenceAuthority.CLASSIFICATION: 3,
    EvidenceAuthority.ENTAILMENT: 4,
}

# Expressivity → admitted concept constructors.
_EXPRESSIVITY_CONSTRUCTORS: Final[Mapping[DLExpressivity, frozenset[ConceptConstructor]]] = {
    DLExpressivity.EL: frozenset(
        {
            ConceptConstructor.ATOMIC,
            ConceptConstructor.TOP,
            ConceptConstructor.AND,
            ConceptConstructor.SOME,
        }
    ),
    DLExpressivity.ALC: frozenset(
        {
            ConceptConstructor.ATOMIC,
            ConceptConstructor.TOP,
            ConceptConstructor.BOTTOM,
            ConceptConstructor.AND,
            ConceptConstructor.OR,
            ConceptConstructor.NOT,
            ConceptConstructor.SOME,
            ConceptConstructor.ONLY,
        }
    ),
    DLExpressivity.ALCQ: frozenset(
        {
            ConceptConstructor.ATOMIC,
            ConceptConstructor.TOP,
            ConceptConstructor.BOTTOM,
            ConceptConstructor.AND,
            ConceptConstructor.OR,
            ConceptConstructor.NOT,
            ConceptConstructor.SOME,
            ConceptConstructor.ONLY,
            ConceptConstructor.MIN,
            ConceptConstructor.MAX,
            ConceptConstructor.EXACTLY,
        }
    ),
}


# ---------------------------------------------------------------------------
# Identity records
# ---------------------------------------------------------------------------


def _require_non_empty_name(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise SyntaxContractError(f"{label} is required")
    if "\x00" in text:
        raise SyntaxContractError(f"{label} must not contain NUL")
    return text


def _require_non_negative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SyntaxContractError(f"{label} must be an integer")
    if value < 0:
        raise SyntaxContractError(f"{label} must be non-negative")
    return value


def _parse_int_literal(text: str, *, label: str = "integer literal") -> int:
    raw = text.strip()
    if not raw:
        raise SyntaxContractError(f"{label} is empty")
    try:
        return int(raw, 10)
    except ValueError as error:
        raise SyntaxContractError(f"invalid {label}: {text!r}") from error


@dataclass(frozen=True, slots=True)
class ConceptIdentity:
    """Explicit concept identity (atomic concept name)."""

    concept_id: str
    schema_version: str = DL_IDENTITY_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "concept_id", _require_non_empty_name(self.concept_id, "concept_id")
        )
        if self.schema_version != DL_IDENTITY_SCHEMA:
            raise SyntaxContractError(
                f"unsupported concept identity schema {self.schema_version!r}"
            )

    @property
    def identity_kind(self) -> str:
        return "concept"

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept_id": self.concept_id,
            "identity_kind": self.identity_kind,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ConceptIdentity:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("ConceptIdentity must be a mapping")
        return cls(
            concept_id=str(value.get("concept_id") or ""),
            schema_version=str(value.get("schema_version") or DL_IDENTITY_SCHEMA),
        )


@dataclass(frozen=True, slots=True)
class RoleIdentity:
    """Explicit role / object-property identity."""

    role_id: str
    schema_version: str = DL_IDENTITY_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "role_id", _require_non_empty_name(self.role_id, "role_id")
        )
        if self.schema_version != DL_IDENTITY_SCHEMA:
            raise SyntaxContractError(
                f"unsupported role identity schema {self.schema_version!r}"
            )

    @property
    def identity_kind(self) -> str:
        return "role"

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity_kind": self.identity_kind,
            "role_id": self.role_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> RoleIdentity:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("RoleIdentity must be a mapping")
        return cls(
            role_id=str(value.get("role_id") or ""),
            schema_version=str(value.get("schema_version") or DL_IDENTITY_SCHEMA),
        )


@dataclass(frozen=True, slots=True)
class IndividualIdentity:
    """Explicit individual / named-entity identity."""

    individual_id: str
    schema_version: str = DL_IDENTITY_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "individual_id",
            _require_non_empty_name(self.individual_id, "individual_id"),
        )
        if self.schema_version != DL_IDENTITY_SCHEMA:
            raise SyntaxContractError(
                f"unsupported individual identity schema {self.schema_version!r}"
            )

    @property
    def identity_kind(self) -> str:
        return "individual"

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity_kind": self.identity_kind,
            "individual_id": self.individual_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> IndividualIdentity:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("IndividualIdentity must be a mapping")
        return cls(
            individual_id=str(value.get("individual_id") or ""),
            schema_version=str(value.get("schema_version") or DL_IDENTITY_SCHEMA),
        )


@dataclass(frozen=True, slots=True)
class CardinalityIdentity:
    """Explicit qualified cardinality bound on a role."""

    cardinality: int
    role_id: str
    kind: str = "min"  # min | max | exactly
    filler_concept_id: str | None = None
    schema_version: str = DL_IDENTITY_SCHEMA

    def __post_init__(self) -> None:
        n = _require_non_negative_int(self.cardinality, "cardinality")
        object.__setattr__(self, "cardinality", n)
        object.__setattr__(
            self, "role_id", _require_non_empty_name(self.role_id, "role_id")
        )
        kind = str(self.kind or "").strip().casefold()
        if kind not in {"min", "max", "exactly"}:
            raise SyntaxContractError(
                f"cardinality kind must be min|max|exactly; got {self.kind!r}"
            )
        object.__setattr__(self, "kind", kind)
        if self.filler_concept_id is not None:
            object.__setattr__(
                self,
                "filler_concept_id",
                _require_non_empty_name(self.filler_concept_id, "filler_concept_id"),
            )
        if self.schema_version != DL_IDENTITY_SCHEMA:
            raise SyntaxContractError(
                f"unsupported cardinality identity schema {self.schema_version!r}"
            )

    @property
    def identity_kind(self) -> str:
        return "cardinality"

    def to_dict(self) -> dict[str, Any]:
        return {
            "cardinality": self.cardinality,
            "filler_concept_id": self.filler_concept_id,
            "identity_kind": self.identity_kind,
            "kind": self.kind,
            "role_id": self.role_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CardinalityIdentity:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("CardinalityIdentity must be a mapping")
        return cls(
            cardinality=int(value["cardinality"]),
            role_id=str(value.get("role_id") or ""),
            kind=str(value.get("kind") or "min"),
            filler_concept_id=(
                str(value["filler_concept_id"])
                if value.get("filler_concept_id") is not None
                else None
            ),
            schema_version=str(value.get("schema_version") or DL_IDENTITY_SCHEMA),
        )


@dataclass(frozen=True, slots=True)
class OntologyImportIdentity:
    """Explicit ontology import identity (IRI or local ontology id)."""

    import_iri: str
    schema_version: str = DL_IDENTITY_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "import_iri",
            _require_non_empty_name(self.import_iri, "import_iri"),
        )
        if self.schema_version != DL_IDENTITY_SCHEMA:
            raise SyntaxContractError(
                f"unsupported import identity schema {self.schema_version!r}"
            )

    @property
    def identity_kind(self) -> str:
        return "ontology_import"

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity_kind": self.identity_kind,
            "import_iri": self.import_iri,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> OntologyImportIdentity:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("OntologyImportIdentity must be a mapping")
        return cls(
            import_iri=str(value.get("import_iri") or ""),
            schema_version=str(value.get("schema_version") or DL_IDENTITY_SCHEMA),
        )


@dataclass(frozen=True, slots=True)
class InclusionIdentity:
    """Explicit concept inclusion (SubClassOf) identity pair."""

    subclass_id: str
    superclass_id: str
    schema_version: str = DL_IDENTITY_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "subclass_id",
            _require_non_empty_name(self.subclass_id, "subclass_id"),
        )
        object.__setattr__(
            self,
            "superclass_id",
            _require_non_empty_name(self.superclass_id, "superclass_id"),
        )
        if self.schema_version != DL_IDENTITY_SCHEMA:
            raise SyntaxContractError(
                f"unsupported inclusion identity schema {self.schema_version!r}"
            )

    @property
    def identity_kind(self) -> str:
        return "inclusion"

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity_kind": self.identity_kind,
            "schema_version": self.schema_version,
            "subclass_id": self.subclass_id,
            "superclass_id": self.superclass_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> InclusionIdentity:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("InclusionIdentity must be a mapping")
        return cls(
            subclass_id=str(value.get("subclass_id") or ""),
            superclass_id=str(value.get("superclass_id") or ""),
            schema_version=str(value.get("schema_version") or DL_IDENTITY_SCHEMA),
        )


@dataclass(frozen=True, slots=True)
class DisjointnessIdentity:
    """Explicit disjoint-classes identity."""

    concept_ids: tuple[str, ...]
    schema_version: str = DL_IDENTITY_SCHEMA

    def __post_init__(self) -> None:
        ids = tuple(
            _require_non_empty_name(item, "concept_id") for item in self.concept_ids
        )
        if len(ids) < 2:
            raise SyntaxContractError(
                "DisjointnessIdentity requires at least two concept_ids"
            )
        object.__setattr__(self, "concept_ids", ids)
        if self.schema_version != DL_IDENTITY_SCHEMA:
            raise SyntaxContractError(
                f"unsupported disjointness identity schema {self.schema_version!r}"
            )

    @property
    def identity_kind(self) -> str:
        return "disjointness"

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept_ids": list(self.concept_ids),
            "identity_kind": self.identity_kind,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> DisjointnessIdentity:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("DisjointnessIdentity must be a mapping")
        raw = value.get("concept_ids") or ()
        return cls(
            concept_ids=tuple(str(item) for item in raw),
            schema_version=str(value.get("schema_version") or DL_IDENTITY_SCHEMA),
        )


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DescriptionLogicProfile:
    """Explicit controlled DL profile (``DescriptionLogicProfile@1``).

    Supported expressivity and open-world semantics are first-class fields.
    Complete OWL and silent FOL approximation are always rejected.
    """

    profile_id: str
    expressivity: DLExpressivity | str = DLExpressivity.ALC
    world_assumption: WorldAssumption | str = WorldAssumption.OPEN_WORLD
    admit_cardinality: bool = False
    admit_disjunction: bool = True
    admit_complement: bool = True
    admit_universal: bool = True
    admit_existential: bool = True
    admit_imports: bool = True
    admit_assertions: bool = True
    allows_fol_approximation: bool = False
    allows_complete_owl: bool = False
    domain: DomainUseCase | str = DomainUseCase.GENERIC
    ontology_id: str | None = None
    schema_version: str = DL_PROFILE_SCHEMA

    interface: ClassVar[str] = DESCRIPTION_LOGIC_PROFILE_INTERFACE

    def __post_init__(self) -> None:
        if not self.profile_id or not str(self.profile_id).strip():
            raise SyntaxContractError(
                "DescriptionLogicProfile.profile_id is required"
            )
        expressivity = (
            self.expressivity
            if isinstance(self.expressivity, DLExpressivity)
            else DLExpressivity(str(self.expressivity))
        )
        world = (
            self.world_assumption
            if isinstance(self.world_assumption, WorldAssumption)
            else WorldAssumption(str(self.world_assumption))
        )
        domain = (
            self.domain
            if isinstance(self.domain, DomainUseCase)
            else DomainUseCase(str(self.domain))
        )
        # Align admit flags with expressivity (caller may tighten, never
        # silently widen beyond the declared expressivity tier).
        if expressivity is DLExpressivity.EL:
            # EL forbids complement, disjunction, universal, cardinality.
            if (
                self.admit_complement
                or self.admit_disjunction
                or self.admit_universal
                or self.admit_cardinality
            ):
                raise SyntaxContractError(
                    "EL expressivity forbids complement, disjunction, "
                    "universal restriction, and cardinality"
                )
        if expressivity is DLExpressivity.ALC and self.admit_cardinality:
            raise SyntaxContractError(
                "ALC expressivity forbids cardinality; use ALCQ"
            )
        if expressivity is DLExpressivity.ALCQ and not self.admit_cardinality:
            # ALCQ implies cardinality is available; force consistent flag.
            object.__setattr__(self, "admit_cardinality", True)

        if self.allows_fol_approximation:
            raise SyntaxContractError(
                "DescriptionLogicProfile.allows_fol_approximation must be False; "
                "unsupported OWL constructs fail without silent FOL approximation"
            )
        if self.allows_complete_owl:
            raise SyntaxContractError(
                "DescriptionLogicProfile.allows_complete_owl must be False; "
                "complete OWL remains declaration-only"
            )
        # Closed-world is allowed only when the caller sets it explicitly;
        # semantic_identity always reports the assumption so it is never silent.

        object.__setattr__(self, "expressivity", expressivity)
        object.__setattr__(self, "world_assumption", world)
        object.__setattr__(self, "domain", domain)
        object.__setattr__(self, "profile_id", str(self.profile_id).strip())
        if self.ontology_id is not None:
            object.__setattr__(
                self,
                "ontology_id",
                _require_non_empty_name(self.ontology_id, "ontology_id"),
            )
        if self.schema_version != DL_PROFILE_SCHEMA:
            raise SyntaxContractError(
                f"unsupported DescriptionLogicProfile schema {self.schema_version!r}"
            )

    @property
    def family_id(self) -> str:
        return DL_FAMILY_ID

    @property
    def is_open_world(self) -> bool:
        return self.world_assumption is WorldAssumption.OPEN_WORLD or (
            isinstance(self.world_assumption, str)
            and self.world_assumption == WorldAssumption.OPEN_WORLD.value
        )

    def admits(self, constructor: ConceptConstructor | str) -> bool:
        ctor = (
            constructor
            if isinstance(constructor, ConceptConstructor)
            else ConceptConstructor(str(constructor))
        )
        expressivity = (
            self.expressivity
            if isinstance(self.expressivity, DLExpressivity)
            else DLExpressivity(str(self.expressivity))
        )
        if ctor not in _EXPRESSIVITY_CONSTRUCTORS[expressivity]:
            return False
        if ctor is ConceptConstructor.OR and not self.admit_disjunction:
            return False
        if ctor is ConceptConstructor.NOT and not self.admit_complement:
            return False
        if ctor is ConceptConstructor.ONLY and not self.admit_universal:
            return False
        if ctor is ConceptConstructor.SOME and not self.admit_existential:
            return False
        if ctor in {
            ConceptConstructor.MIN,
            ConceptConstructor.MAX,
            ConceptConstructor.EXACTLY,
        } and not self.admit_cardinality:
            return False
        return True

    @property
    def semantic_identity(self) -> dict[str, Any]:
        expressivity = (
            self.expressivity.value
            if isinstance(self.expressivity, DLExpressivity)
            else str(self.expressivity)
        )
        world = (
            self.world_assumption.value
            if isinstance(self.world_assumption, WorldAssumption)
            else str(self.world_assumption)
        )
        domain = (
            self.domain.value
            if isinstance(self.domain, DomainUseCase)
            else str(self.domain)
        )
        return {
            "admit_assertions": self.admit_assertions,
            "admit_cardinality": self.admit_cardinality,
            "admit_complement": self.admit_complement,
            "admit_disjunction": self.admit_disjunction,
            "admit_existential": self.admit_existential,
            "admit_imports": self.admit_imports,
            "admit_universal": self.admit_universal,
            "allows_complete_owl": False,
            "allows_fol_approximation": False,
            "domain": domain,
            "expressivity": expressivity,
            "family": DL_FAMILY_ID,
            "ontology_id": self.ontology_id,
            "profile_id": self.profile_id,
            "world_assumption": world,
        }

    def identities(self) -> dict[str, Any]:
        """Explicit profile-level identity projection."""

        return {
            "expressivity": (
                self.expressivity.value
                if isinstance(self.expressivity, DLExpressivity)
                else str(self.expressivity)
            ),
            "ontology_id": self.ontology_id,
            "profile_id": self.profile_id,
            "schema_version": DL_IDENTITY_SCHEMA,
            "world_assumption": (
                self.world_assumption.value
                if isinstance(self.world_assumption, WorldAssumption)
                else str(self.world_assumption)
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "admit_assertions": self.admit_assertions,
            "admit_cardinality": self.admit_cardinality,
            "admit_complement": self.admit_complement,
            "admit_disjunction": self.admit_disjunction,
            "admit_existential": self.admit_existential,
            "admit_imports": self.admit_imports,
            "admit_universal": self.admit_universal,
            "allows_complete_owl": False,
            "allows_fol_approximation": False,
            "domain": (
                self.domain.value
                if isinstance(self.domain, DomainUseCase)
                else str(self.domain)
            ),
            "expressivity": (
                self.expressivity.value
                if isinstance(self.expressivity, DLExpressivity)
                else str(self.expressivity)
            ),
            "interface": self.interface,
            "ontology_id": self.ontology_id,
            "profile_id": self.profile_id,
            "schema_version": self.schema_version,
            "world_assumption": (
                self.world_assumption.value
                if isinstance(self.world_assumption, WorldAssumption)
                else str(self.world_assumption)
            ),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> DescriptionLogicProfile:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("DescriptionLogicProfile must be a mapping")
        return cls(
            profile_id=str(value.get("profile_id") or ""),
            expressivity=value.get("expressivity", DLExpressivity.ALC.value),
            world_assumption=value.get(
                "world_assumption", WorldAssumption.OPEN_WORLD.value
            ),
            admit_cardinality=bool(value.get("admit_cardinality", False)),
            admit_disjunction=bool(value.get("admit_disjunction", True)),
            admit_complement=bool(value.get("admit_complement", True)),
            admit_universal=bool(value.get("admit_universal", True)),
            admit_existential=bool(value.get("admit_existential", True)),
            admit_imports=bool(value.get("admit_imports", True)),
            admit_assertions=bool(value.get("admit_assertions", True)),
            allows_fol_approximation=bool(
                value.get("allows_fol_approximation", False)
            ),
            allows_complete_owl=bool(value.get("allows_complete_owl", False)),
            domain=value.get("domain", DomainUseCase.GENERIC.value),
            ontology_id=(
                str(value["ontology_id"])
                if value.get("ontology_id") is not None
                else None
            ),
            schema_version=str(value.get("schema_version") or DL_PROFILE_SCHEMA),
        )


# Alias used in domain-facing APIs.
OntologyProfile = DescriptionLogicProfile


def profile_alc(
    *,
    profile_id: str = "dl_alc",
    domain: DomainUseCase | str = DomainUseCase.GENERIC,
    ontology_id: str | None = None,
) -> DescriptionLogicProfile:
    """ALC profile: conjunction, disjunction, complement, some, only."""

    return DescriptionLogicProfile(
        profile_id=profile_id,
        expressivity=DLExpressivity.ALC,
        world_assumption=WorldAssumption.OPEN_WORLD,
        admit_cardinality=False,
        admit_disjunction=True,
        admit_complement=True,
        admit_universal=True,
        admit_existential=True,
        domain=domain,
        ontology_id=ontology_id,
    )


def profile_alcq(
    *,
    profile_id: str = "dl_alcq",
    domain: DomainUseCase | str = DomainUseCase.GENERIC,
    ontology_id: str | None = None,
) -> DescriptionLogicProfile:
    """ALCQ profile: ALC plus qualified number restrictions."""

    return DescriptionLogicProfile(
        profile_id=profile_id,
        expressivity=DLExpressivity.ALCQ,
        world_assumption=WorldAssumption.OPEN_WORLD,
        admit_cardinality=True,
        admit_disjunction=True,
        admit_complement=True,
        admit_universal=True,
        admit_existential=True,
        domain=domain,
        ontology_id=ontology_id,
    )


def profile_el(
    *,
    profile_id: str = "dl_el",
    domain: DomainUseCase | str = DomainUseCase.GENERIC,
    ontology_id: str | None = None,
) -> DescriptionLogicProfile:
    """EL profile: top, conjunction, existential only (no complement/or/only)."""

    return DescriptionLogicProfile(
        profile_id=profile_id,
        expressivity=DLExpressivity.EL,
        world_assumption=WorldAssumption.OPEN_WORLD,
        admit_cardinality=False,
        admit_disjunction=False,
        admit_complement=False,
        admit_universal=False,
        admit_existential=True,
        domain=domain,
        ontology_id=ontology_id,
    )


def profile_legal_ontology(
    *,
    profile_id: str = "ontology_legal_alcq",
    ontology_id: str = "ontology:legal:v1",
) -> DescriptionLogicProfile:
    """Legal IR ontology profile (ALCQ, open-world)."""

    return profile_alcq(
        profile_id=profile_id,
        domain=DomainUseCase.LEGAL,
        ontology_id=ontology_id,
    )


def profile_ui_ontology(
    *,
    profile_id: str = "ontology_ui_alc",
    ontology_id: str = "ontology:ui:v1",
) -> DescriptionLogicProfile:
    """UI/UX IR ontology profile (ALC, open-world)."""

    return profile_alc(
        profile_id=profile_id,
        domain=DomainUseCase.UI,
        ontology_id=ontology_id,
    )


def profile_intent_ontology(
    *,
    profile_id: str = "ontology_intent_alc",
    ontology_id: str = "ontology:intent:v1",
) -> DescriptionLogicProfile:
    """Intent IR ontology profile (ALC, open-world)."""

    return profile_alc(
        profile_id=profile_id,
        domain=DomainUseCase.INTENT,
        ontology_id=ontology_id,
    )


def profile_kg_ontology(
    *,
    profile_id: str = "ontology_kg_alcq",
    ontology_id: str = "ontology:kg:v1",
) -> DescriptionLogicProfile:
    """Knowledge-graph ontology profile (ALCQ, open-world)."""

    return profile_alcq(
        profile_id=profile_id,
        domain=DomainUseCase.KNOWLEDGE_GRAPH,
        ontology_id=ontology_id,
    )


def description_logic_semantic_identity(
    node: LogicNode,
    profile: DescriptionLogicProfile,
) -> dict[str, Any]:
    """Stable semantic identity including expressivity and open-world flag."""

    extracted = extract_dl_identities(node)
    return {
        "extracted": extracted,
        "family": DL_FAMILY_ID,
        "node_kind": (
            node.kind.value if isinstance(node.kind, NodeKind) else str(node.kind)
        ),
        "profile": profile.semantic_identity,
        "profile_identities": profile.identities(),
        "world_assumption": (
            profile.world_assumption.value
            if isinstance(profile.world_assumption, WorldAssumption)
            else str(profile.world_assumption)
        ),
    }


# ---------------------------------------------------------------------------
# Evidence contracts — FOL approximation never becomes DL authority
# ---------------------------------------------------------------------------


class AuthorityPromotionError(SyntaxContractError):
    """Raised when evidence is promoted beyond its declared authority ceiling."""


@dataclass(frozen=True, slots=True)
class DescriptionLogicEvidenceContract:
    """Authority ceiling for description-logic / ontology evidence.

    FOL approximation evidence is advisory only and **cannot** become
    classification or entailment authority.
    """

    source: EvidenceSource | str
    authority: EvidenceAuthority | str
    expressivity: DLExpressivity | str = DLExpressivity.ALC
    world_assumption: WorldAssumption | str = WorldAssumption.OPEN_WORLD
    grants_entailment_authority: bool = False
    schema_version: str = DL_EVIDENCE_CONTRACT_SCHEMA

    interface: ClassVar[str] = DESCRIPTION_LOGIC_PROFILES_INTERFACE

    def __post_init__(self) -> None:
        source = (
            self.source
            if isinstance(self.source, EvidenceSource)
            else EvidenceSource(str(self.source))
        )
        authority = (
            self.authority
            if isinstance(self.authority, EvidenceAuthority)
            else EvidenceAuthority(str(self.authority))
        )
        expressivity = (
            self.expressivity
            if isinstance(self.expressivity, DLExpressivity)
            else DLExpressivity(str(self.expressivity))
        )
        world = (
            self.world_assumption
            if isinstance(self.world_assumption, WorldAssumption)
            else WorldAssumption(str(self.world_assumption))
        )
        ceiling = _SOURCE_AUTHORITY_CEILING[source]
        if _AUTHORITY_RANK[authority] > _AUTHORITY_RANK[ceiling]:
            raise AuthorityPromotionError(
                f"{source.value} evidence cannot claim {authority.value} "
                f"authority (ceiling={ceiling.value}); FOL approximation "
                "cannot become DL entailment authority"
            )
        if source is EvidenceSource.FOL_APPROXIMATION:
            if authority not in {
                EvidenceAuthority.NONE,
                EvidenceAuthority.ADVISORY,
            }:
                raise AuthorityPromotionError(
                    "FOL approximation evidence cannot become classification "
                    "or entailment authority; unsupported OWL constructs fail "
                    "without silent FOL approximation"
                )
            if self.grants_entailment_authority:
                raise AuthorityPromotionError(
                    "FOL approximation cannot grant entailment authority"
                )
        if authority is EvidenceAuthority.ENTAILMENT:
            if source not in {
                EvidenceSource.TABLEAU_REASONER,
                EvidenceSource.OWL_REASONER,
            }:
                raise AuthorityPromotionError(
                    f"{source.value} cannot claim entailment authority"
                )
            if not self.grants_entailment_authority:
                raise AuthorityPromotionError(
                    f"{source.value} cannot claim entailment without "
                    "grants_entailment_authority from a DL reasoner path"
                )
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "authority", authority)
        object.__setattr__(self, "expressivity", expressivity)
        object.__setattr__(self, "world_assumption", world)
        if self.schema_version != DL_EVIDENCE_CONTRACT_SCHEMA:
            raise SyntaxContractError(
                f"unsupported evidence contract schema {self.schema_version!r}"
            )

    @property
    def authority_ceiling(self) -> EvidenceAuthority:
        assert isinstance(self.authority, EvidenceAuthority)
        return self.authority

    @property
    def may_promote_to_entailment(self) -> bool:
        return False if self.source is EvidenceSource.FOL_APPROXIMATION else False

    def promote_to_entailment(self) -> None:
        """Fail closed: FOL approximation never becomes entailment authority."""

        source = (
            self.source.value
            if isinstance(self.source, EvidenceSource)
            else str(self.source)
        )
        raise AuthorityPromotionError(
            f"{source} evidence cannot be promoted to entailment authority; "
            "unsupported OWL constructs fail without silent FOL approximation"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority_ceiling.value,
            "authority_ceiling": self.authority_ceiling.value,
            "expressivity": (
                self.expressivity.value
                if isinstance(self.expressivity, DLExpressivity)
                else str(self.expressivity)
            ),
            "grants_entailment_authority": bool(self.grants_entailment_authority),
            "interface": self.interface,
            "may_promote_to_entailment": False,
            "schema_version": self.schema_version,
            "source": (
                self.source.value
                if isinstance(self.source, EvidenceSource)
                else str(self.source)
            ),
            "world_assumption": (
                self.world_assumption.value
                if isinstance(self.world_assumption, WorldAssumption)
                else str(self.world_assumption)
            ),
        }


def fol_approximation_evidence_contract(
    profile: DescriptionLogicProfile | None = None,
) -> DescriptionLogicEvidenceContract:
    """FOL approximation is advisory only; never DL entailment authority."""

    return DescriptionLogicEvidenceContract(
        source=EvidenceSource.FOL_APPROXIMATION,
        authority=EvidenceAuthority.ADVISORY,
        expressivity=(
            profile.expressivity if profile is not None else DLExpressivity.ALC
        ),
        world_assumption=(
            profile.world_assumption
            if profile is not None
            else WorldAssumption.OPEN_WORLD
        ),
        grants_entailment_authority=False,
    )


def local_classifier_evidence_contract(
    profile: DescriptionLogicProfile | None = None,
) -> DescriptionLogicEvidenceContract:
    """Local classifier evidence: bounded only."""

    return DescriptionLogicEvidenceContract(
        source=EvidenceSource.LOCAL_CLASSIFIER,
        authority=EvidenceAuthority.BOUNDED,
        expressivity=(
            profile.expressivity if profile is not None else DLExpressivity.ALC
        ),
        world_assumption=(
            profile.world_assumption
            if profile is not None
            else WorldAssumption.OPEN_WORLD
        ),
        grants_entailment_authority=False,
    )


def tableau_reasoner_evidence_contract(
    profile: DescriptionLogicProfile | None = None,
    *,
    grants_entailment_authority: bool = False,
) -> DescriptionLogicEvidenceContract:
    """Tableau reasoner path; entailment requires explicit grant."""

    authority = (
        EvidenceAuthority.ENTAILMENT
        if grants_entailment_authority
        else EvidenceAuthority.BOUNDED
    )
    return DescriptionLogicEvidenceContract(
        source=EvidenceSource.TABLEAU_REASONER,
        authority=authority,
        expressivity=(
            profile.expressivity if profile is not None else DLExpressivity.ALC
        ),
        world_assumption=(
            profile.world_assumption
            if profile is not None
            else WorldAssumption.OPEN_WORLD
        ),
        grants_entailment_authority=grants_entailment_authority,
    )


def reject_fol_approximation(
    *,
    construct: str,
    message: str | None = None,
) -> SyntaxDiagnostic:
    """Build a fail-closed diagnostic for attempted FOL approximation."""

    return _diag(
        code=CODE_FOL_APPROXIMATION_REJECTED,
        message=message
        or (
            f"refusing silent FOL approximation of unsupported OWL construct "
            f"{construct!r}; declare a controlled DL profile subset or fail"
        ),
        range=SourceRange(0, 0),
        remediation=(
            "Use only profile-admitted constructors (ALC/ALCQ/EL); "
            "do not lower unsupported OWL to FOL silently"
        ),
        metadata={"construct": construct, "allows_fol_approximation": False},
    )


# ---------------------------------------------------------------------------
# Result envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DescriptionLogicParseResult:
    """Typed result of a description-logic parse attempt."""

    status: ParseStatus
    root: LogicNode | None = None
    expression: TypedExpression | None = None
    diagnostics: tuple[SyntaxDiagnostic, ...] = ()
    tokens: tuple[LogicToken, ...] = ()
    artifact: ParseArtifact | None = None
    printed: str = ""
    profile: DescriptionLogicProfile | None = None
    identities: dict[str, Any] = field(default_factory=dict)
    schema_version: str = DL_PARSE_RESULT_SCHEMA

    interface: ClassVar[str] = DESCRIPTION_LOGIC_PROFILES_INTERFACE

    @property
    def ok(self) -> bool:
        return self.status is ParseStatus.OK and self.root is not None

    @property
    def errors(self) -> tuple[SyntaxDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.is_error)

    def to_dict(self) -> dict[str, Any]:
        return {
            "identities": dict(self.identities),
            "interface": self.interface,
            "printed": self.printed,
            "profile": self.profile.to_dict() if self.profile else None,
            "schema_version": self.schema_version,
            "status": (
                self.status.value
                if isinstance(self.status, ParseStatus)
                else str(self.status)
            ),
        }


class DescriptionLogicParseError(SyntaxContractError):
    """Raised by raising helpers when a DL parse fails closed."""

    def __init__(
        self,
        message: str,
        *,
        code: str = CODE_UNEXPECTED_TOKEN,
        diagnostics: Sequence[SyntaxDiagnostic] = (),
        result: DescriptionLogicParseResult | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.diagnostics = tuple(diagnostics)
        self.result = result


# ---------------------------------------------------------------------------
# Diagnostics / cursor
# ---------------------------------------------------------------------------


class _ParseFail(Exception):
    def __init__(self, diagnostic: SyntaxDiagnostic) -> None:
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic


def _diag(
    *,
    code: str,
    message: str,
    range: SourceRange | None,
    remediation: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> SyntaxDiagnostic:
    return SyntaxDiagnostic(
        diagnostic_id=f"diag:dl:{code.replace('.', '-')}",
        code=code,
        message=message,
        severity=DiagnosticSeverity.ERROR,
        range=range or SourceRange(0, 0),
        remediation=remediation,
        metadata=dict(metadata or {}),
    )


class _Cursor:
    def __init__(
        self,
        tokens: Sequence[LogicToken],
        document: SourceDocument,
    ) -> None:
        self.tokens = tuple(tokens)
        self.document = document
        self.index = 0
        self.depth = 0

    def current(self) -> LogicToken:
        if self.index >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[self.index]

    def peek(self, offset: int = 1) -> LogicToken:
        pos = self.index + offset
        if pos >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[pos]

    def is_eof(self) -> bool:
        return self.current().kind == TokenKind.EOF.value

    def advance(self) -> LogicToken:
        token = self.current()
        if not self.is_eof():
            self.index += 1
        return token

    def match_any(self, lexemes: frozenset[str]) -> LogicToken | None:
        token = self.current()
        if token.kind == TokenKind.EOF.value:
            return None
        folded = {item.casefold() for item in lexemes}
        if token.lexeme in lexemes or token.lexeme.casefold() in folded:
            return self.advance()
        return None

    def match_lexeme(self, *lexemes: str) -> LogicToken | None:
        return self.match_any(frozenset(lexemes))

    def expect_lexeme(
        self, *lexemes: str, code: str = CODE_UNEXPECTED_TOKEN
    ) -> LogicToken:
        token = self.match_lexeme(*lexemes)
        if token is not None:
            return token
        current = self.current()
        expected = " or ".join(repr(item) for item in lexemes)
        raise _ParseFail(
            _diag(
                code=code,
                message=f"expected {expected}; got {current.lexeme!r}",
                range=current.range,
            )
        )

    def expect_number(self) -> LogicToken:
        token = self.current()
        if token.kind == TokenKind.NUMBER.value:
            return self.advance()
        raise _ParseFail(
            _diag(
                code=CODE_UNEXPECTED_TOKEN,
                message=f"expected number; got {token.lexeme!r}",
                range=token.range,
            )
        )

    def expect_ident(self) -> LogicToken:
        token = self.current()
        if token.kind in {
            TokenKind.IDENTIFIER.value,
            TokenKind.KEYWORD.value,
            TokenKind.STRING.value,
        }:
            return self.advance()
        raise _ParseFail(
            _diag(
                code=CODE_UNEXPECTED_TOKEN,
                message=f"expected identifier; got {token.lexeme!r}",
                range=token.range,
            )
        )

    def range_span(self, start: SourceRange, end: SourceRange) -> SourceRange:
        if (
            start.start_char is not None
            and start.end_char is not None
            and end.start_char is not None
            and end.end_char is not None
        ):
            return SourceRange(
                start=start.start,
                end=end.end,
                start_char=start.start_char,
                end_char=end.end_char,
            )
        return SourceRange(start=start.start, end=end.end)


# ---------------------------------------------------------------------------
# Identity extraction from AST
# ---------------------------------------------------------------------------


def extract_dl_identities(node: LogicNode) -> dict[str, Any]:
    """Walk a DL AST and collect explicit identity fragments."""

    concepts: list[str] = []
    roles: list[str] = []
    individuals: list[str] = []
    axioms: list[str] = []
    cardinalities: list[dict[str, Any]] = []
    imports: list[str] = []
    inclusions: list[dict[str, str]] = []
    disjointness: list[list[str]] = []

    def walk(n: LogicNode) -> None:
        ext = n.extension
        if ext is not None:
            payload = dict(ext.payload)
            schema = ext.payload_schema
            if schema == DL_CONCEPT_ATOMIC_SCHEMA:
                name = str(payload.get("concept_id") or "")
                if name:
                    concepts.append(name)
            elif schema == DL_ROLE_ATOMIC_SCHEMA:
                name = str(payload.get("role_id") or "")
                if name:
                    roles.append(name)
            elif schema == DL_INDIVIDUAL_SCHEMA:
                name = str(payload.get("individual_id") or "")
                if name:
                    individuals.append(name)
            elif schema == DL_AXIOM_SUBCLASS_SCHEMA:
                axioms.append(AxiomKind.SUBCLASS_OF.value)
                inclusions.append(
                    {
                        "subclass_id": str(payload.get("subclass_id") or ""),
                        "superclass_id": str(payload.get("superclass_id") or ""),
                    }
                )
            elif schema == DL_AXIOM_EQUIV_SCHEMA:
                axioms.append(AxiomKind.EQUIVALENT_CLASSES.value)
            elif schema == DL_AXIOM_DISJOINT_SCHEMA:
                axioms.append(AxiomKind.DISJOINT_CLASSES.value)
                ids = payload.get("concept_ids") or []
                if isinstance(ids, (list, tuple)):
                    disjointness.append([str(item) for item in ids])
            elif schema == DL_AXIOM_CLASS_ASSERT_SCHEMA:
                axioms.append(AxiomKind.CLASS_ASSERTION.value)
            elif schema == DL_AXIOM_ROLE_ASSERT_SCHEMA:
                axioms.append(AxiomKind.OBJECT_PROPERTY_ASSERTION.value)
            elif schema == DL_IMPORT_SCHEMA:
                axioms.append(AxiomKind.IMPORT.value)
                iri = str(payload.get("import_iri") or "")
                if iri:
                    imports.append(iri)
            elif schema in {
                DL_CONCEPT_MIN_SCHEMA,
                DL_CONCEPT_MAX_SCHEMA,
                DL_CONCEPT_EXACTLY_SCHEMA,
            }:
                cardinalities.append(
                    {
                        "cardinality": int(payload.get("cardinality", 0)),
                        "kind": str(payload.get("kind") or ""),
                        "role_id": str(payload.get("role_id") or ""),
                        "filler_concept_id": payload.get("filler_concept_id"),
                    }
                )
                role = str(payload.get("role_id") or "")
                if role:
                    roles.append(role)
            elif schema in {DL_CONCEPT_SOME_SCHEMA, DL_CONCEPT_ONLY_SCHEMA}:
                role = str(payload.get("role_id") or "")
                if role:
                    roles.append(role)
            for child in ext.children:
                walk(child)
        for child in n.arguments:
            walk(child)

    walk(node)
    return {
        "axioms": list(dict.fromkeys(axioms)),
        "cardinalities": cardinalities,
        "concepts": sorted(set(concepts)),
        "disjointness": disjointness,
        "imports": list(dict.fromkeys(imports)),
        "inclusions": inclusions,
        "individuals": sorted(set(individuals)),
        "roles": sorted(set(roles)),
        "schema_version": DL_IDENTITY_SCHEMA,
    }


# ---------------------------------------------------------------------------
# Parser engine
# ---------------------------------------------------------------------------


class _DLParserEngine:
    """Recursive-descent description-logic / ontology parser."""

    def __init__(
        self,
        *,
        document: SourceDocument,
        tokens: Sequence[LogicToken],
        profile: DescriptionLogicProfile,
        limits: ParseLimits,
        expression_id: str,
    ) -> None:
        self.document = document
        self.cursor = _Cursor(tokens, document)
        self.profile = profile
        self.limits = limits
        self.expression_id = expression_id
        self._counter = 0
        self._concepts: list[str] = []
        self._roles: list[str] = []
        self._individuals: list[str] = []
        self._imports: list[str] = []

    def _nid(self, prefix: str) -> str:
        self._counter += 1
        return f"{self.expression_id}:{prefix}:{self._counter}"

    def _enter(self) -> None:
        self.cursor.depth += 1
        if self.cursor.depth > self.limits.max_depth:
            raise _ParseFail(
                _diag(
                    code=CODE_PARSE_DEPTH,
                    message=(
                        f"parse depth {self.cursor.depth} exceeds limit "
                        f"{self.limits.max_depth}"
                    ),
                    range=self.cursor.current().range,
                )
            )

    def _leave(self) -> None:
        self.cursor.depth = max(0, self.cursor.depth - 1)

    def parse(self) -> tuple[LogicNode | None, tuple[SyntaxDiagnostic, ...]]:
        if not self.document.text.strip():
            return None, (
                _diag(
                    code=CODE_EMPTY_INPUT,
                    message="empty description-logic input is rejected",
                    range=self.document.full_range(),
                ),
            )
        try:
            root = self._parse_document()
            if not self.cursor.is_eof():
                tok = self.cursor.current()
                raise _ParseFail(
                    _diag(
                        code=CODE_TRAILING_INPUT,
                        message=f"trailing input starting at {tok.lexeme!r}",
                        range=tok.range,
                        remediation=(
                            "Remove trailing tokens or close open constructs"
                        ),
                    )
                )
            return root, ()
        except _ParseFail as error:
            return None, (error.diagnostic,)

    def _parse_document(self) -> LogicNode:
        self._enter()
        try:
            statements: list[LogicNode] = []
            statements.append(self._parse_statement())
            while not self.cursor.is_eof():
                # Soft separators between axioms.
                if self.cursor.match_lexeme(";", ".") is not None:
                    if self.cursor.is_eof():
                        break
                    statements.append(self._parse_statement())
                    continue
                # Adjacent statements without separator.
                nxt = self.cursor.current()
                if nxt.lexeme.casefold() in _AXIOM_ATOMS or (
                    nxt.lexeme.casefold() in _UNSUPPORTED_OWL_KEYWORDS
                ):
                    statements.append(self._parse_statement())
                    continue
                break
            if len(statements) == 1:
                return statements[0]
            span = self.cursor.range_span(
                statements[0].range or SourceRange(0, 0),
                statements[-1].range or SourceRange(0, 0),
            )
            payload = {
                "axiom_count": len(statements),
                "ontology_id": self.profile.ontology_id,
                "profile_id": self.profile.profile_id,
                "schema_version": DL_ONTOLOGY_DOC_SCHEMA,
                "world_assumption": (
                    self.profile.world_assumption.value
                    if isinstance(self.profile.world_assumption, WorldAssumption)
                    else str(self.profile.world_assumption)
                ),
            }
            return mk_extension(
                self._nid("ontology"),
                family=DL_FAMILY_ID,
                profile=self.profile.profile_id,
                features=("description_logic.ontology.document",),
                payload_schema=DL_ONTOLOGY_DOC_SCHEMA,
                payload=payload,
                children=tuple(statements),
                range=span,
            )
        finally:
            self._leave()

    def _parse_statement(self) -> LogicNode:
        self._enter()
        try:
            token = self.cursor.current()
            name = token.lexeme.casefold()

            # Fail closed on unsupported OWL keywords — no FOL approximation.
            if name in _UNSUPPORTED_OWL_KEYWORDS:
                raise _ParseFail(
                    _diag(
                        code=CODE_UNSUPPORTED_OWL,
                        message=(
                            f"unsupported OWL construct {token.lexeme!r} is "
                            f"rejected under profile "
                            f"{self.profile.profile_id!r} "
                            f"(expressivity="
                            f"{self.profile.expressivity.value if isinstance(self.profile.expressivity, DLExpressivity) else self.profile.expressivity}); "
                            "no silent FOL approximation is performed"
                        ),
                        range=token.range,
                        remediation=(
                            "Use only controlled ALC/ALCQ/EL constructors and "
                            "axioms; complete OWL remains declaration-only"
                        ),
                        metadata={
                            "allows_fol_approximation": False,
                            "construct": token.lexeme,
                            "expressivity": (
                                self.profile.expressivity.value
                                if isinstance(
                                    self.profile.expressivity, DLExpressivity
                                )
                                else str(self.profile.expressivity)
                            ),
                        },
                    )
                )

            if name in _AXIOM_ATOMS and token.kind in {
                TokenKind.IDENTIFIER.value,
                TokenKind.KEYWORD.value,
            }:
                return self._parse_axiom(name)

            # Bare concept is not a statement; require an axiom form.
            raise _ParseFail(
                _diag(
                    code=CODE_UNEXPECTED_TOKEN,
                    message=(
                        f"expected axiom or import; got {token.lexeme!r}"
                    ),
                    range=token.range,
                    remediation=(
                        "Use SubClassOf(...), EquivalentClasses(...), "
                        "DisjointClasses(...), ClassAssertion(...), "
                        "ObjectPropertyAssertion(...), or Import(...)"
                    ),
                )
            )
        finally:
            self._leave()

    def _parse_axiom(self, name: str) -> LogicNode:
        start = self.cursor.advance()

        if name == "import":
            if not self.profile.admit_imports:
                raise _ParseFail(
                    _diag(
                        code=CODE_PROFILE_MISMATCH,
                        message=(
                            f"Import is not admitted by profile "
                            f"{self.profile.profile_id!r}"
                        ),
                        range=start.range,
                    )
                )
            self.cursor.expect_lexeme("(", code=CODE_UNBALANCED)
            iri_tok = self.cursor.expect_ident()
            iri = iri_tok.lexeme.strip("\"'")
            end = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            span = self.cursor.range_span(start.range, end.range)
            return self._build_import(iri, span)

        if name == "subclassof":
            self.cursor.expect_lexeme("(", code=CODE_UNBALANCED)
            sub = self._parse_concept()
            self.cursor.expect_lexeme(",")
            sup = self._parse_concept()
            end = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            span = self.cursor.range_span(start.range, end.range)
            return self._build_subclass(sub, sup, span)

        if name == "equivalentclasses":
            self.cursor.expect_lexeme("(", code=CODE_UNBALANCED)
            concepts = self._parse_concept_list(min_count=2)
            end = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            span = self.cursor.range_span(start.range, end.range)
            return self._build_equivalent(concepts, span)

        if name == "disjointclasses":
            self.cursor.expect_lexeme("(", code=CODE_UNBALANCED)
            concepts = self._parse_concept_list(min_count=2)
            end = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            span = self.cursor.range_span(start.range, end.range)
            return self._build_disjoint(concepts, span)

        if name == "classassertion":
            if not self.profile.admit_assertions:
                raise _ParseFail(
                    _diag(
                        code=CODE_PROFILE_MISMATCH,
                        message=(
                            f"ClassAssertion is not admitted by profile "
                            f"{self.profile.profile_id!r}"
                        ),
                        range=start.range,
                    )
                )
            self.cursor.expect_lexeme("(", code=CODE_UNBALANCED)
            concept = self._parse_concept()
            self.cursor.expect_lexeme(",")
            individual = self._parse_individual()
            end = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            span = self.cursor.range_span(start.range, end.range)
            return self._build_class_assertion(concept, individual, span)

        if name == "objectpropertyassertion":
            if not self.profile.admit_assertions:
                raise _ParseFail(
                    _diag(
                        code=CODE_PROFILE_MISMATCH,
                        message=(
                            f"ObjectPropertyAssertion is not admitted by "
                            f"profile {self.profile.profile_id!r}"
                        ),
                        range=start.range,
                    )
                )
            self.cursor.expect_lexeme("(", code=CODE_UNBALANCED)
            role = self._parse_role()
            self.cursor.expect_lexeme(",")
            subj = self._parse_individual()
            self.cursor.expect_lexeme(",")
            obj = self._parse_individual()
            end = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            span = self.cursor.range_span(start.range, end.range)
            return self._build_role_assertion(role, subj, obj, span)

        raise _ParseFail(
            _diag(
                code=CODE_UNSUPPORTED_OWL,
                message=f"unsupported axiom form {name!r}",
                range=start.range,
                metadata={"allows_fol_approximation": False, "construct": name},
            )
        )

    def _parse_concept_list(self, *, min_count: int) -> list[LogicNode]:
        items: list[LogicNode] = [self._parse_concept()]
        while self.cursor.match_lexeme(",") is not None:
            items.append(self._parse_concept())
        if len(items) < min_count:
            raise _ParseFail(
                _diag(
                    code=CODE_ARITY_MISMATCH,
                    message=(
                        f"expected at least {min_count} concepts; got {len(items)}"
                    ),
                    range=self.cursor.current().range,
                )
            )
        return items

    def _parse_concept(self) -> LogicNode:
        self._enter()
        try:
            token = self.cursor.current()
            name = token.lexeme.casefold()

            if name in _UNSUPPORTED_OWL_KEYWORDS:
                raise _ParseFail(
                    _diag(
                        code=CODE_UNSUPPORTED_OWL,
                        message=(
                            f"unsupported OWL concept constructor "
                            f"{token.lexeme!r}; no silent FOL approximation"
                        ),
                        range=token.range,
                        metadata={
                            "allows_fol_approximation": False,
                            "construct": token.lexeme,
                        },
                    )
                )

            if name == "(":
                self.cursor.advance()
                inner = self._parse_concept()
                self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
                return inner

            if name in {"thing", "⊤"}:
                start = self.cursor.advance()
                return self._build_top(start.range)

            if name in {"nothing", "⊥"}:
                start = self.cursor.advance()
                return self._build_bottom(start.range)

            if name in _CONCEPT_CONSTRUCTORS and token.kind in {
                TokenKind.IDENTIFIER.value,
                TokenKind.KEYWORD.value,
            }:
                return self._parse_concept_constructor(name)

            if token.kind in {
                TokenKind.IDENTIFIER.value,
                TokenKind.KEYWORD.value,
            }:
                # Atomic concept.
                start = self.cursor.advance()
                return self._build_atomic_concept(start.lexeme, start.range)

            raise _ParseFail(
                _diag(
                    code=CODE_UNEXPECTED_TOKEN,
                    message=f"expected concept; got {token.lexeme!r}",
                    range=token.range,
                )
            )
        finally:
            self._leave()

    def _parse_concept_constructor(self, name: str) -> LogicNode:
        start = self.cursor.advance()

        if name == "and":
            self._require_constructor(ConceptConstructor.AND, start.range)
            self.cursor.expect_lexeme("(", code=CODE_UNBALANCED)
            children = self._parse_concept_list(min_count=2)
            end = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            span = self.cursor.range_span(start.range, end.range)
            return self._build_and(children, span)

        if name == "or":
            self._require_constructor(ConceptConstructor.OR, start.range)
            self.cursor.expect_lexeme("(", code=CODE_UNBALANCED)
            children = self._parse_concept_list(min_count=2)
            end = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            span = self.cursor.range_span(start.range, end.range)
            return self._build_or(children, span)

        if name == "not":
            self._require_constructor(ConceptConstructor.NOT, start.range)
            self.cursor.expect_lexeme("(", code=CODE_UNBALANCED)
            child = self._parse_concept()
            end = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            span = self.cursor.range_span(start.range, end.range)
            return self._build_not(child, span)

        if name == "some":
            self._require_constructor(ConceptConstructor.SOME, start.range)
            self.cursor.expect_lexeme("(", code=CODE_UNBALANCED)
            role = self._parse_role()
            self.cursor.expect_lexeme(",")
            filler = self._parse_concept()
            end = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            span = self.cursor.range_span(start.range, end.range)
            return self._build_some(role, filler, span)

        if name in {"only", "all"}:
            self._require_constructor(ConceptConstructor.ONLY, start.range)
            self.cursor.expect_lexeme("(", code=CODE_UNBALANCED)
            role = self._parse_role()
            self.cursor.expect_lexeme(",")
            filler = self._parse_concept()
            end = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            span = self.cursor.range_span(start.range, end.range)
            return self._build_only(role, filler, span)

        if name in {"min", "max", "exactly"}:
            ctor = {
                "min": ConceptConstructor.MIN,
                "max": ConceptConstructor.MAX,
                "exactly": ConceptConstructor.EXACTLY,
            }[name]
            self._require_constructor(ctor, start.range)
            self.cursor.expect_lexeme("(", code=CODE_UNBALANCED)
            num = self.cursor.expect_number()
            n = _parse_int_literal(num.lexeme, label="cardinality")
            self.cursor.expect_lexeme(",")
            role = self._parse_role()
            filler: LogicNode | None = None
            if self.cursor.match_lexeme(",") is not None:
                filler = self._parse_concept()
            end = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            span = self.cursor.range_span(start.range, end.range)
            return self._build_cardinality(name, n, role, filler, span)

        # thing/nothing handled upstream
        raise _ParseFail(
            _diag(
                code=CODE_UNEXPECTED_TOKEN,
                message=f"unknown concept constructor {name!r}",
                range=start.range,
            )
        )

    def _require_constructor(
        self, constructor: ConceptConstructor, span: SourceRange
    ) -> None:
        if not self.profile.admits(constructor):
            expressivity = (
                self.profile.expressivity.value
                if isinstance(self.profile.expressivity, DLExpressivity)
                else str(self.profile.expressivity)
            )
            raise _ParseFail(
                _diag(
                    code=CODE_PROFILE_MISMATCH,
                    message=(
                        f"concept constructor {constructor.value!r} is not "
                        f"admitted by profile {self.profile.profile_id!r} "
                        f"(expressivity={expressivity})"
                    ),
                    range=span,
                    remediation=(
                        f"Use a profile that admits {constructor.value} "
                        f"(e.g. ALCQ for cardinality, ALC for complement/or)"
                    ),
                    metadata={
                        "constructor": constructor.value,
                        "expressivity": expressivity,
                        "profile_id": self.profile.profile_id,
                    },
                )
            )

    def _parse_role(self) -> LogicNode:
        token = self.cursor.current()
        name = token.lexeme.casefold()
        if name in _UNSUPPORTED_OWL_KEYWORDS:
            raise _ParseFail(
                _diag(
                    code=CODE_UNSUPPORTED_OWL,
                    message=(
                        f"unsupported OWL role construct {token.lexeme!r}; "
                        "no silent FOL approximation"
                    ),
                    range=token.range,
                    metadata={
                        "allows_fol_approximation": False,
                        "construct": token.lexeme,
                    },
                )
            )
        if token.kind not in {
            TokenKind.IDENTIFIER.value,
            TokenKind.KEYWORD.value,
            TokenKind.STRING.value,
        }:
            raise _ParseFail(
                _diag(
                    code=CODE_UNEXPECTED_TOKEN,
                    message=f"expected role name; got {token.lexeme!r}",
                    range=token.range,
                )
            )
        start = self.cursor.advance()
        role_id = start.lexeme.strip("\"'")
        self._roles.append(role_id)
        payload = {
            "profile_id": self.profile.profile_id,
            "role_id": role_id,
            "schema_version": DL_ROLE_ATOMIC_SCHEMA,
        }
        return mk_extension(
            self._nid("role"),
            family=DL_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("description_logic.role.atomic",),
            payload_schema=DL_ROLE_ATOMIC_SCHEMA,
            payload=payload,
            sort=ROLE_SORT,
            range=start.range,
        )

    def _parse_individual(self) -> LogicNode:
        token = self.cursor.current()
        if token.kind not in {
            TokenKind.IDENTIFIER.value,
            TokenKind.KEYWORD.value,
            TokenKind.STRING.value,
        }:
            raise _ParseFail(
                _diag(
                    code=CODE_UNEXPECTED_TOKEN,
                    message=f"expected individual name; got {token.lexeme!r}",
                    range=token.range,
                )
            )
        start = self.cursor.advance()
        individual_id = start.lexeme.strip("\"'")
        self._individuals.append(individual_id)
        payload = {
            "individual_id": individual_id,
            "profile_id": self.profile.profile_id,
            "schema_version": DL_INDIVIDUAL_SCHEMA,
        }
        return mk_extension(
            self._nid("ind"),
            family=DL_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("description_logic.individual",),
            payload_schema=DL_INDIVIDUAL_SCHEMA,
            payload=payload,
            sort=INDIVIDUAL_DL_SORT,
            range=start.range,
        )

    # -- builders -----------------------------------------------------------

    def _concept_label(self, node: LogicNode) -> str:
        ext = node.extension
        if ext is None:
            return "?"
        payload = dict(ext.payload)
        if ext.payload_schema == DL_CONCEPT_ATOMIC_SCHEMA:
            return str(payload.get("concept_id") or "?")
        if ext.payload_schema == DL_CONCEPT_TOP_SCHEMA:
            return "Thing"
        if ext.payload_schema == DL_CONCEPT_BOTTOM_SCHEMA:
            return "Nothing"
        return ext.payload_schema.split(".")[-1].split("/")[0]

    def _role_label(self, node: LogicNode) -> str:
        ext = node.extension
        if ext is None:
            return "?"
        return str(dict(ext.payload).get("role_id") or "?")

    def _build_atomic_concept(self, name: str, span: SourceRange) -> LogicNode:
        self._require_constructor(ConceptConstructor.ATOMIC, span)
        self._concepts.append(name)
        payload = {
            "concept_id": name,
            "profile_id": self.profile.profile_id,
            "schema_version": DL_CONCEPT_ATOMIC_SCHEMA,
        }
        return mk_extension(
            self._nid("concept"),
            family=DL_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("description_logic.concept.atomic",),
            payload_schema=DL_CONCEPT_ATOMIC_SCHEMA,
            payload=payload,
            sort=CONCEPT_SORT,
            range=span,
        )

    def _build_top(self, span: SourceRange) -> LogicNode:
        self._require_constructor(ConceptConstructor.TOP, span)
        payload = {
            "concept_id": "Thing",
            "kind": ConceptConstructor.TOP.value,
            "profile_id": self.profile.profile_id,
            "schema_version": DL_CONCEPT_TOP_SCHEMA,
        }
        return mk_extension(
            self._nid("top"),
            family=DL_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("description_logic.concept.top",),
            payload_schema=DL_CONCEPT_TOP_SCHEMA,
            payload=payload,
            sort=CONCEPT_SORT,
            range=span,
        )

    def _build_bottom(self, span: SourceRange) -> LogicNode:
        self._require_constructor(ConceptConstructor.BOTTOM, span)
        payload = {
            "concept_id": "Nothing",
            "kind": ConceptConstructor.BOTTOM.value,
            "profile_id": self.profile.profile_id,
            "schema_version": DL_CONCEPT_BOTTOM_SCHEMA,
        }
        return mk_extension(
            self._nid("bottom"),
            family=DL_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("description_logic.concept.bottom",),
            payload_schema=DL_CONCEPT_BOTTOM_SCHEMA,
            payload=payload,
            sort=CONCEPT_SORT,
            range=span,
        )

    def _build_and(
        self, children: Sequence[LogicNode], span: SourceRange
    ) -> LogicNode:
        payload = {
            "kind": ConceptConstructor.AND.value,
            "profile_id": self.profile.profile_id,
            "schema_version": DL_CONCEPT_AND_SCHEMA,
        }
        return mk_extension(
            self._nid("and"),
            family=DL_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("description_logic.concept.and",),
            payload_schema=DL_CONCEPT_AND_SCHEMA,
            payload=payload,
            children=tuple(children),
            sort=CONCEPT_SORT,
            range=span,
        )

    def _build_or(
        self, children: Sequence[LogicNode], span: SourceRange
    ) -> LogicNode:
        payload = {
            "kind": ConceptConstructor.OR.value,
            "profile_id": self.profile.profile_id,
            "schema_version": DL_CONCEPT_OR_SCHEMA,
        }
        return mk_extension(
            self._nid("or"),
            family=DL_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("description_logic.concept.or",),
            payload_schema=DL_CONCEPT_OR_SCHEMA,
            payload=payload,
            children=tuple(children),
            sort=CONCEPT_SORT,
            range=span,
        )

    def _build_not(self, child: LogicNode, span: SourceRange) -> LogicNode:
        payload = {
            "kind": ConceptConstructor.NOT.value,
            "profile_id": self.profile.profile_id,
            "schema_version": DL_CONCEPT_NOT_SCHEMA,
        }
        return mk_extension(
            self._nid("not"),
            family=DL_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("description_logic.concept.not",),
            payload_schema=DL_CONCEPT_NOT_SCHEMA,
            payload=payload,
            children=(child,),
            sort=CONCEPT_SORT,
            range=span,
        )

    def _build_some(
        self, role: LogicNode, filler: LogicNode, span: SourceRange
    ) -> LogicNode:
        payload = {
            "kind": ConceptConstructor.SOME.value,
            "profile_id": self.profile.profile_id,
            "role_id": self._role_label(role),
            "schema_version": DL_CONCEPT_SOME_SCHEMA,
        }
        return mk_extension(
            self._nid("some"),
            family=DL_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("description_logic.concept.some",),
            payload_schema=DL_CONCEPT_SOME_SCHEMA,
            payload=payload,
            children=(role, filler),
            sort=CONCEPT_SORT,
            range=span,
        )

    def _build_only(
        self, role: LogicNode, filler: LogicNode, span: SourceRange
    ) -> LogicNode:
        payload = {
            "kind": ConceptConstructor.ONLY.value,
            "profile_id": self.profile.profile_id,
            "role_id": self._role_label(role),
            "schema_version": DL_CONCEPT_ONLY_SCHEMA,
        }
        return mk_extension(
            self._nid("only"),
            family=DL_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("description_logic.concept.only",),
            payload_schema=DL_CONCEPT_ONLY_SCHEMA,
            payload=payload,
            children=(role, filler),
            sort=CONCEPT_SORT,
            range=span,
        )

    def _build_cardinality(
        self,
        kind: str,
        n: int,
        role: LogicNode,
        filler: LogicNode | None,
        span: SourceRange,
    ) -> LogicNode:
        if n < 0:
            raise _ParseFail(
                _diag(
                    code=CODE_INVALID_CARDINALITY,
                    message=f"cardinality must be non-negative; got {n}",
                    range=span,
                )
            )
        schema = {
            "min": DL_CONCEPT_MIN_SCHEMA,
            "max": DL_CONCEPT_MAX_SCHEMA,
            "exactly": DL_CONCEPT_EXACTLY_SCHEMA,
        }[kind]
        role_id = self._role_label(role)
        filler_id = self._concept_label(filler) if filler is not None else None
        payload = {
            "cardinality": n,
            "filler_concept_id": filler_id,
            "kind": kind,
            "profile_id": self.profile.profile_id,
            "role_id": role_id,
            "schema_version": schema,
        }
        children: list[LogicNode] = [role]
        if filler is not None:
            children.append(filler)
        return mk_extension(
            self._nid(kind),
            family=DL_FAMILY_ID,
            profile=self.profile.profile_id,
            features=(f"description_logic.concept.{kind}",),
            payload_schema=schema,
            payload=payload,
            children=tuple(children),
            sort=CONCEPT_SORT,
            range=span,
        )

    def _build_import(self, iri: str, span: SourceRange) -> LogicNode:
        identity = OntologyImportIdentity(import_iri=iri)
        self._imports.append(identity.import_iri)
        payload = {
            "import_iri": identity.import_iri,
            "ontology_id": self.profile.ontology_id,
            "profile_id": self.profile.profile_id,
            "schema_version": DL_IMPORT_SCHEMA,
        }
        return mk_extension(
            self._nid("import"),
            family=DL_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("description_logic.ontology.import",),
            payload_schema=DL_IMPORT_SCHEMA,
            payload=payload,
            sort=ONTOLOGY_SORT,
            range=span,
        )

    def _build_subclass(
        self, sub: LogicNode, sup: LogicNode, span: SourceRange
    ) -> LogicNode:
        payload = {
            "kind": AxiomKind.SUBCLASS_OF.value,
            "profile_id": self.profile.profile_id,
            "schema_version": DL_AXIOM_SUBCLASS_SCHEMA,
            "subclass_id": self._concept_label(sub),
            "superclass_id": self._concept_label(sup),
            "world_assumption": (
                self.profile.world_assumption.value
                if isinstance(self.profile.world_assumption, WorldAssumption)
                else str(self.profile.world_assumption)
            ),
        }
        return mk_extension(
            self._nid("subclass"),
            family=DL_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("description_logic.axiom.subclass_of",),
            payload_schema=DL_AXIOM_SUBCLASS_SCHEMA,
            payload=payload,
            children=(sub, sup),
            range=span,
        )

    def _build_equivalent(
        self, concepts: Sequence[LogicNode], span: SourceRange
    ) -> LogicNode:
        ids = [self._concept_label(c) for c in concepts]
        payload = {
            "concept_ids": ids,
            "kind": AxiomKind.EQUIVALENT_CLASSES.value,
            "profile_id": self.profile.profile_id,
            "schema_version": DL_AXIOM_EQUIV_SCHEMA,
            "world_assumption": (
                self.profile.world_assumption.value
                if isinstance(self.profile.world_assumption, WorldAssumption)
                else str(self.profile.world_assumption)
            ),
        }
        return mk_extension(
            self._nid("equiv"),
            family=DL_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("description_logic.axiom.equivalent_classes",),
            payload_schema=DL_AXIOM_EQUIV_SCHEMA,
            payload=payload,
            children=tuple(concepts),
            range=span,
        )

    def _build_disjoint(
        self, concepts: Sequence[LogicNode], span: SourceRange
    ) -> LogicNode:
        ids = [self._concept_label(c) for c in concepts]
        payload = {
            "concept_ids": ids,
            "kind": AxiomKind.DISJOINT_CLASSES.value,
            "profile_id": self.profile.profile_id,
            "schema_version": DL_AXIOM_DISJOINT_SCHEMA,
            "world_assumption": (
                self.profile.world_assumption.value
                if isinstance(self.profile.world_assumption, WorldAssumption)
                else str(self.profile.world_assumption)
            ),
        }
        return mk_extension(
            self._nid("disjoint"),
            family=DL_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("description_logic.axiom.disjoint_classes",),
            payload_schema=DL_AXIOM_DISJOINT_SCHEMA,
            payload=payload,
            children=tuple(concepts),
            range=span,
        )

    def _build_class_assertion(
        self, concept: LogicNode, individual: LogicNode, span: SourceRange
    ) -> LogicNode:
        payload = {
            "concept_id": self._concept_label(concept),
            "individual_id": str(
                dict(individual.extension.payload).get("individual_id")
                if individual.extension
                else "?"
            ),
            "kind": AxiomKind.CLASS_ASSERTION.value,
            "profile_id": self.profile.profile_id,
            "schema_version": DL_AXIOM_CLASS_ASSERT_SCHEMA,
            "world_assumption": (
                self.profile.world_assumption.value
                if isinstance(self.profile.world_assumption, WorldAssumption)
                else str(self.profile.world_assumption)
            ),
        }
        return mk_extension(
            self._nid("class_assert"),
            family=DL_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("description_logic.axiom.class_assertion",),
            payload_schema=DL_AXIOM_CLASS_ASSERT_SCHEMA,
            payload=payload,
            children=(concept, individual),
            range=span,
        )

    def _build_role_assertion(
        self,
        role: LogicNode,
        subject: LogicNode,
        obj: LogicNode,
        span: SourceRange,
    ) -> LogicNode:
        payload = {
            "kind": AxiomKind.OBJECT_PROPERTY_ASSERTION.value,
            "object_id": str(
                dict(obj.extension.payload).get("individual_id")
                if obj.extension
                else "?"
            ),
            "profile_id": self.profile.profile_id,
            "role_id": self._role_label(role),
            "schema_version": DL_AXIOM_ROLE_ASSERT_SCHEMA,
            "subject_id": str(
                dict(subject.extension.payload).get("individual_id")
                if subject.extension
                else "?"
            ),
            "world_assumption": (
                self.profile.world_assumption.value
                if isinstance(self.profile.world_assumption, WorldAssumption)
                else str(self.profile.world_assumption)
            ),
        }
        return mk_extension(
            self._nid("role_assert"),
            family=DL_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("description_logic.axiom.object_property_assertion",),
            payload_schema=DL_AXIOM_ROLE_ASSERT_SCHEMA,
            payload=payload,
            children=(role, subject, obj),
            range=span,
        )


# ---------------------------------------------------------------------------
# Printer
# ---------------------------------------------------------------------------


class DescriptionLogicPrinter:
    """Deterministic printer for description-logic / ontology ASTs."""

    def __init__(self, *, style: str = PrintStyle.ASCII) -> None:
        if style not in {PrintStyle.ASCII, PrintStyle.UNICODE}:
            raise SyntaxContractError(
                f"print style must be 'ascii' or 'unicode'; got {style!r}"
            )
        self.style = style

    def print(self, node: LogicNode | TypedExpression) -> str:
        if isinstance(node, TypedExpression):
            return self._print_node(node.root)
        if not isinstance(node, LogicNode):
            raise SyntaxContractError(
                "print requires a LogicNode or TypedExpression"
            )
        return self._print_node(node)

    def _print_node(self, node: LogicNode) -> str:
        kind = node.kind
        if kind is NodeKind.TRUE or kind == NodeKind.TRUE.value:
            return "true"
        if kind is NodeKind.FALSE or kind == NodeKind.FALSE.value:
            return "false"
        if kind is NodeKind.EXTENSION or kind == NodeKind.EXTENSION.value:
            return self._print_extension(node)
        raise SyntaxContractError(
            f"cannot print node kind "
            f"{kind.value if isinstance(kind, NodeKind) else kind}"
        )

    def _print_extension(self, node: LogicNode) -> str:
        ext = node.extension
        if ext is None:
            raise SyntaxContractError("EXTENSION node missing extension payload")
        schema = ext.payload_schema
        payload = dict(ext.payload)
        children = list(ext.children)

        if schema == DL_ONTOLOGY_DOC_SCHEMA:
            return "; ".join(self._print_node(c) for c in children)

        if schema == DL_IMPORT_SCHEMA:
            iri = str(payload["import_iri"])
            # Always quote so IRIs with ':', '/', '.' round-trip as one token.
            escaped = iri.replace("\\", "\\\\").replace('"', '\\"')
            return f'Import("{escaped}")'

        if schema == DL_AXIOM_SUBCLASS_SCHEMA:
            return (
                f"SubClassOf({self._print_node(children[0])}, "
                f"{self._print_node(children[1])})"
            )

        if schema == DL_AXIOM_EQUIV_SCHEMA:
            parts = ", ".join(self._print_node(c) for c in children)
            return f"EquivalentClasses({parts})"

        if schema == DL_AXIOM_DISJOINT_SCHEMA:
            parts = ", ".join(self._print_node(c) for c in children)
            return f"DisjointClasses({parts})"

        if schema == DL_AXIOM_CLASS_ASSERT_SCHEMA:
            return (
                f"ClassAssertion({self._print_node(children[0])}, "
                f"{self._print_node(children[1])})"
            )

        if schema == DL_AXIOM_ROLE_ASSERT_SCHEMA:
            return (
                f"ObjectPropertyAssertion({self._print_node(children[0])}, "
                f"{self._print_node(children[1])}, "
                f"{self._print_node(children[2])})"
            )

        if schema == DL_CONCEPT_ATOMIC_SCHEMA:
            return str(payload.get("concept_id") or "?")

        if schema == DL_CONCEPT_TOP_SCHEMA:
            return "Thing" if self.style == PrintStyle.ASCII else "⊤"

        if schema == DL_CONCEPT_BOTTOM_SCHEMA:
            return "Nothing" if self.style == PrintStyle.ASCII else "⊥"

        if schema == DL_CONCEPT_AND_SCHEMA:
            parts = ", ".join(self._print_node(c) for c in children)
            return f"and({parts})"

        if schema == DL_CONCEPT_OR_SCHEMA:
            parts = ", ".join(self._print_node(c) for c in children)
            return f"or({parts})"

        if schema == DL_CONCEPT_NOT_SCHEMA:
            return f"not({self._print_node(children[0])})"

        if schema == DL_CONCEPT_SOME_SCHEMA:
            return (
                f"some({self._print_node(children[0])}, "
                f"{self._print_node(children[1])})"
            )

        if schema == DL_CONCEPT_ONLY_SCHEMA:
            return (
                f"only({self._print_node(children[0])}, "
                f"{self._print_node(children[1])})"
            )

        if schema == DL_CONCEPT_MIN_SCHEMA:
            return self._print_card("min", payload, children)

        if schema == DL_CONCEPT_MAX_SCHEMA:
            return self._print_card("max", payload, children)

        if schema == DL_CONCEPT_EXACTLY_SCHEMA:
            return self._print_card("exactly", payload, children)

        if schema == DL_ROLE_ATOMIC_SCHEMA:
            return str(payload.get("role_id") or "?")

        if schema == DL_INDIVIDUAL_SCHEMA:
            return str(payload.get("individual_id") or "?")

        raise SyntaxContractError(f"cannot print extension schema {schema!r}")

    def _print_card(
        self,
        kind: str,
        payload: Mapping[str, Any],
        children: Sequence[LogicNode],
    ) -> str:
        role = self._print_node(children[0])
        n = payload["cardinality"]
        if len(children) > 1:
            return f"{kind}({n}, {role}, {self._print_node(children[1])})"
        return f"{kind}({n}, {role})"


# ---------------------------------------------------------------------------
# Parser facade
# ---------------------------------------------------------------------------


def _extract_profile(value: object) -> DescriptionLogicProfile | None:
    if value is None:
        return None
    if isinstance(value, DescriptionLogicProfile):
        return value
    if isinstance(value, Mapping):
        return DescriptionLogicProfile.from_dict(value)
    return None


def _build_covering_cst(
    document: SourceDocument,
    tokens: Sequence[LogicToken],
    *,
    cst_id: str = "cst:dl:1",
) -> LogicCST:
    children = tuple(
        LogicCSTNode(
            node_id=f"node:{token.token_id}",
            kind=token.kind,
            range=token.range,
            role=CSTNodeRole.TOKEN,
            token_id=token.token_id,
        )
        for token in tokens
        if token.kind != TokenKind.EOF.value
    )
    covered = [token.range for token in tokens if token.kind != TokenKind.EOF.value]
    holes: list[LogicCSTNode] = []
    cursor = 0
    for item in sorted(covered, key=lambda value: value.start):
        if item.start > cursor:
            holes.append(
                LogicCSTNode(
                    node_id=f"node:gap:{cursor}:{item.start}",
                    kind="gap",
                    range=SourceRange(start=cursor, end=item.start),
                    role=CSTNodeRole.GAP,
                )
            )
        cursor = max(cursor, item.end)
    if cursor < document.byte_length:
        holes.append(
            LogicCSTNode(
                node_id=f"node:gap:{cursor}:{document.byte_length}",
                kind="gap",
                range=SourceRange(start=cursor, end=document.byte_length),
                role=CSTNodeRole.GAP,
            )
        )
    leaves = tuple(sorted((*children, *holes), key=lambda node: node.range.start))
    if not leaves and document.byte_length == 0:
        root = LogicCSTNode(
            node_id="node:root",
            kind="source_file",
            range=document.full_range(),
            role=CSTNodeRole.ROOT,
            children=(),
        )
    else:
        root = LogicCSTNode(
            node_id="node:root",
            kind="source_file",
            range=document.full_range(),
            role=CSTNodeRole.ROOT,
            children=leaves,
        )
    return LogicCST(
        cst_id=cst_id,
        document_id=document.document_id,
        root=root,
        source_length=document.byte_length,
    )


def _surface_from_node(node: LogicNode) -> list[SurfaceASTRef]:
    refs: list[SurfaceASTRef] = []
    seq = [0]

    def walk(n: LogicNode) -> str:
        seq[0] += 1
        node_id = n.node_id if n.node_id else f"ast:{seq[0]}"
        child_ids: list[str] = []
        for child in n.arguments:
            child_ids.append(walk(child))
        if n.extension is not None:
            for child in n.extension.children:
                child_ids.append(walk(child))
        kind = n.kind.value if isinstance(n.kind, NodeKind) else str(n.kind)
        safe_kind = kind.replace(" ", "_")
        span = n.range or SourceRange(0, 0)
        meta: dict[str, Any] = {}
        if n.symbol:
            meta["symbol"] = n.symbol
        if n.extension is not None:
            meta["payload_schema"] = n.extension.payload_schema
            meta["features"] = list(n.extension.features)
        refs.append(
            SurfaceASTRef(
                node_id=node_id,
                kind=safe_kind,
                range=span,
                child_ids=tuple(child_ids),
                metadata=meta,
            )
        )
        return node_id

    walk(node)
    return refs


def _signature_for_ontology(
    root: LogicNode,
    profile: DescriptionLogicProfile,
) -> LogicSignature:
    del root
    return LogicSignature(
        signature_id=f"sig:description_logic:{profile.profile_id}",
        family=DL_FAMILY_ID,
        profile=profile.profile_id,
        sorts=(CONCEPT_SORT, ROLE_SORT, INDIVIDUAL_DL_SORT, ONTOLOGY_SORT, BOOL_SORT),
        symbols=(),
        features=("description_logic", "ontology", "open_world"),
    )


class DescriptionLogicParser:
    """Notation parser for controlled description-logic / ontology syntax.

    Interface: ``DescriptionLogicProfiles@1``.
    """

    interface: ClassVar[str] = DESCRIPTION_LOGIC_PROFILES_INTERFACE
    notation_id: ClassVar[str] = DL_NOTATION_ID
    notation_version: ClassVar[str] = DL_NOTATION_VERSION

    def __init__(
        self,
        profile: DescriptionLogicProfile | None = None,
        *,
        print_style: str = PrintStyle.ASCII,
    ) -> None:
        if profile is not None and not isinstance(profile, DescriptionLogicProfile):
            raise SyntaxContractError(
                "profile must be a DescriptionLogicProfile"
            )
        self.profile = profile
        self.printer = DescriptionLogicPrinter(style=print_style)
        self._lexer = BoundedLexer(keywords=_DL_KEYWORDS)

    def parse(self, request: ParseRequest) -> ParseArtifact:
        if not isinstance(request, ParseRequest):
            raise SyntaxContractError("parse requires a ParseRequest")
        profile = (
            _extract_profile(request.metadata.get("profile"))
            or _extract_profile(request.metadata.get("description_logic_profile"))
            or self.profile
        )
        result = self.parse_document(
            request.document,
            profile=profile,
            mode=request.mode,
            limits=request.limits,
            request_id=request.request_id,
            expression_id=str(
                request.metadata.get("expression_id") or "expr:dl:1"
            ),
        )
        assert result.artifact is not None
        return result.artifact

    def parse_document(
        self,
        document: SourceDocument,
        *,
        profile: DescriptionLogicProfile | None = None,
        mode: ParseMode | str = ParseMode.STRICT,
        limits: ParseLimits | None = None,
        request_id: str = "req:dl:1",
        expression_id: str = "expr:dl:1",
    ) -> DescriptionLogicParseResult:
        if not isinstance(document, SourceDocument):
            raise SyntaxContractError("document must be a SourceDocument")
        bounds = limits if limits is not None else ParseLimits()
        parse_mode = mode if isinstance(mode, ParseMode) else ParseMode(str(mode))
        prof = profile or self.profile
        if prof is None:
            diag = _diag(
                code=CODE_PROFILE_MISMATCH,
                message=(
                    "description-logic parse requires a DescriptionLogicProfile"
                ),
                range=document.full_range(),
                remediation="Pass profile=profile_alc() or profile_alcq()",
            )
            artifact = ParseArtifact(
                artifact_id=f"art:{request_id}",
                request_id=request_id,
                document_id=document.document_id,
                status=ParseStatus.REJECTED,
                tokens=(),
                diagnostics=(diag,),
                metadata={"interface": DESCRIPTION_LOGIC_PROFILES_INTERFACE},
            )
            return DescriptionLogicParseResult(
                status=ParseStatus.REJECTED,
                diagnostics=(diag,),
                artifact=artifact,
            )

        lex_result = self._lexer.lex(document, mode=parse_mode, limits=bounds)
        if lex_result.status is not ParseStatus.OK and any(
            item.is_error for item in lex_result.diagnostics
        ):
            promoted = tuple(
                SyntaxDiagnostic(
                    diagnostic_id=f"diag:dl:lex:{index + 1}",
                    code=(
                        CODE_UNKNOWN_CHARACTER
                        if "unknown" in item.code
                        else (
                            CODE_LEXER_ERROR
                            if item.code.startswith("lexer.")
                            else item.code
                        )
                    ),
                    message=item.message,
                    severity=item.severity,
                    range=item.range,
                    remediation=item.remediation
                    or "Unknown characters no longer disappear; fix or remove them",
                    metadata={"lexer_code": item.code},
                )
                for index, item in enumerate(lex_result.diagnostics)
            )
            artifact = ParseArtifact(
                artifact_id=f"art:{request_id}",
                request_id=request_id,
                document_id=document.document_id,
                status=ParseStatus.FAILED,
                tokens=lex_result.tokens,
                diagnostics=promoted,
                metadata={"interface": DESCRIPTION_LOGIC_PROFILES_INTERFACE},
            )
            return DescriptionLogicParseResult(
                status=ParseStatus.FAILED,
                diagnostics=promoted,
                tokens=lex_result.tokens,
                artifact=artifact,
                profile=prof,
            )

        engine = _DLParserEngine(
            document=document,
            tokens=lex_result.tokens,
            profile=prof,
            limits=bounds,
            expression_id=expression_id,
        )
        root, diagnostics = engine.parse()
        all_diags = tuple(lex_result.diagnostics) + tuple(diagnostics)

        if root is None or any(item.is_error for item in all_diags):
            artifact = ParseArtifact(
                artifact_id=f"art:{request_id}",
                request_id=request_id,
                document_id=document.document_id,
                status=ParseStatus.FAILED,
                tokens=lex_result.tokens,
                diagnostics=all_diags,
                metadata={
                    "interface": DESCRIPTION_LOGIC_PROFILES_INTERFACE,
                    "profile": prof.to_dict(),
                },
            )
            return DescriptionLogicParseResult(
                status=ParseStatus.FAILED,
                diagnostics=all_diags,
                tokens=lex_result.tokens,
                artifact=artifact,
                profile=prof,
            )

        printed = self.printer.print(root)
        extracted = extract_dl_identities(root)
        identities = {
            **prof.identities(),
            "extracted": extracted,
        }
        signature = _signature_for_ontology(root, prof)
        expression = TypedExpression(
            expression_id=expression_id,
            root=root,
            signature=signature,
            family=DL_FAMILY_ID,
            profile=prof.profile_id,
            range=root.range,
            elaborate_on_init=False,
        )
        cst = _build_covering_cst(document, lex_result.tokens)
        surface = tuple(_surface_from_node(root))
        artifact = ParseArtifact(
            artifact_id=f"art:{request_id}",
            request_id=request_id,
            document_id=document.document_id,
            status=ParseStatus.OK,
            tokens=lex_result.tokens,
            cst=cst,
            surface_ast=surface,
            diagnostics=all_diags,
            metadata={
                "interface": DESCRIPTION_LOGIC_PROFILES_INTERFACE,
                "profile": prof.to_dict(),
                "identities": identities,
                "printed": printed,
                "world_assumption": (
                    prof.world_assumption.value
                    if isinstance(prof.world_assumption, WorldAssumption)
                    else str(prof.world_assumption)
                ),
                "allows_fol_approximation": False,
            },
        )
        return DescriptionLogicParseResult(
            status=ParseStatus.OK,
            root=root,
            expression=expression,
            diagnostics=all_diags,
            tokens=lex_result.tokens,
            artifact=artifact,
            printed=printed,
            profile=prof,
            identities=identities,
        )


class DescriptionLogicProfiles:
    """Facade for ``DescriptionLogicProfiles@1``."""

    interface: ClassVar[str] = DESCRIPTION_LOGIC_PROFILES_INTERFACE

    def __init__(
        self,
        profile: DescriptionLogicProfile | None = None,
        *,
        print_style: str = PrintStyle.ASCII,
    ) -> None:
        self.profile = profile or profile_alc()
        self.parser = DescriptionLogicParser(self.profile, print_style=print_style)
        self.printer = DescriptionLogicPrinter(style=print_style)

    def parse_text(self, text: str, **kwargs: Any) -> DescriptionLogicParseResult:
        document_id = str(kwargs.pop("document_id", "doc:dl:1"))
        mode = kwargs.pop("mode", ParseMode.STRICT)
        limits = kwargs.pop("limits", None)
        request_id = str(kwargs.pop("request_id", "req:dl:1"))
        expression_id = str(kwargs.pop("expression_id", "expr:dl:1"))
        document = SourceDocument.from_text(document_id, text, encoding="utf-8")
        return self.parser.parse_document(
            document,
            profile=self.profile,
            mode=mode,
            limits=limits,
            request_id=request_id,
            expression_id=expression_id,
        )

    def parse_text_or_raise(self, text: str, **kwargs: Any) -> TypedExpression:
        result = self.parse_text(text, **kwargs)
        if not result.ok or result.expression is None:
            raise DescriptionLogicParseError(
                "description-logic parse failed",
                diagnostics=result.diagnostics,
                result=result,
            )
        return result.expression

    def print(self, node: LogicNode | TypedExpression) -> str:
        return self.printer.print(node)


def parse_description_logic(
    text: str,
    profile: DescriptionLogicProfile | None = None,
    **kwargs: Any,
) -> DescriptionLogicParseResult:
    """Parse description-logic / ontology *text* under *profile*."""

    logic = DescriptionLogicProfiles(profile or profile_alc())
    return logic.parse_text(text, **kwargs)


def print_description_logic(
    node: LogicNode | TypedExpression,
    *,
    style: str = PrintStyle.ASCII,
) -> str:
    return DescriptionLogicPrinter(style=style).print(node)


def parse_print_parse(
    text: str,
    profile: DescriptionLogicProfile | None = None,
) -> tuple[DescriptionLogicParseResult, DescriptionLogicParseResult, bool]:
    """Parse, print, re-parse; return both results and alpha-equivalence."""

    prof = profile or profile_alc()
    first = parse_description_logic(text, prof)
    if not first.ok or first.root is None:
        return first, first, False
    printed = print_description_logic(first.root)
    second = parse_description_logic(printed, prof)
    if not second.ok or second.root is None:
        return first, second, False
    equivalent = alpha_equivalent(first.root, second.root)
    return first, second, equivalent


__all__ = [
    "DESCRIPTION_LOGIC_PROFILES_INTERFACE",
    "DESCRIPTION_LOGIC_PROFILE_INTERFACE",
    "ONTOLOGY_PROFILE_INTERFACE",
    "DL_FAMILY_ID",
    "DL_NOTATION_ID",
    "AuthorityPromotionError",
    "AxiomKind",
    "CardinalityIdentity",
    "ConceptConstructor",
    "ConceptIdentity",
    "DLExpressivity",
    "DescriptionLogicEvidenceContract",
    "DescriptionLogicParseError",
    "DescriptionLogicParseResult",
    "DescriptionLogicParser",
    "DescriptionLogicPrinter",
    "DescriptionLogicProfile",
    "DescriptionLogicProfiles",
    "DisjointnessIdentity",
    "DomainUseCase",
    "EvidenceAuthority",
    "EvidenceSource",
    "InclusionIdentity",
    "IndividualIdentity",
    "OntologyImportIdentity",
    "OntologyProfile",
    "PrintStyle",
    "RoleIdentity",
    "WorldAssumption",
    "description_logic_semantic_identity",
    "extract_dl_identities",
    "fol_approximation_evidence_contract",
    "local_classifier_evidence_contract",
    "parse_description_logic",
    "parse_print_parse",
    "print_description_logic",
    "profile_alc",
    "profile_alcq",
    "profile_el",
    "profile_intent_ontology",
    "profile_kg_ontology",
    "profile_legal_ontology",
    "profile_ui_ontology",
    "reject_fol_approximation",
    "tableau_reasoner_evidence_contract",
    # diagnostic codes
    "CODE_UNSUPPORTED_OWL",
    "CODE_FOL_APPROXIMATION_REJECTED",
    "CODE_PROFILE_MISMATCH",
    "CODE_OPEN_WORLD_VIOLATION",
    "CODE_COMPLETE_OWL_REJECTED",
]
