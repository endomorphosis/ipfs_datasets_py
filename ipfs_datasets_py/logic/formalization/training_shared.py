"""Closed, content-addressed training-example and semantic-trace contracts.

The records in this module are the admission boundary between source-grounded
formalization artifacts and proof-grounded IR learning.  They are deliberately
domain neutral and additive to the existing formalization contracts.  Decoding
a structurally valid candidate is separate from admitting it for training:
unknown, model-only, rights-blocked, non-training-split, timeout, and unchecked
records remain representable, but fail closed at :class:`IRTrainingExample`.

Every durable identity uses the shared ``ir-canonical-identity-v1`` profile.
All dependency bindings use explicit identifiers *and* ``sha256:<hex>``
digests.  Arbitrary logic families, relationships, authority labels, outcomes,
or quarantine reasons are rejected rather than silently widened.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.ir_core.claims import ClaimValidationError, FrozenMap
from ipfs_datasets_py.logic.ir_core.identity import CanonicalIdentity, canonical_identity
from ipfs_datasets_py.logic.ir_core.protocols import AuthorityKind
from ipfs_datasets_py.logic.ir_core.source_lineage import RightsDisposition

from .samples import FormalizationValidationError

# ---------------------------------------------------------------------------
# Interface and schema identities
# ---------------------------------------------------------------------------

LINEAGE_BINDING_INTERFACE: Final = "IRTrainingLineage@1"
STATEMENT_BINDING_INTERFACE: Final = "IRStatementBinding@1"
TOOL_BINDING_INTERFACE: Final = "IRToolBinding@1"
LABEL_EVIDENCE_INTERFACE: Final = "IRLabelEvidence@1"
TRACE_REFERENCE_INTERFACE: Final = "IRTraceReference@1"
TACTIC_STEP_INTERFACE: Final = "IRTacticStep@1"

IR_COMPILER_TRACE_INTERFACE: Final = "IRCompilerTrace@1"
IR_DECOMPILER_TRACE_INTERFACE: Final = "IRDecompilerTrace@1"
IR_TRANSLATION_TRACE_INTERFACE: Final = "IRTranslationTrace@1"
IR_ROUND_TRIP_TRACE_INTERFACE: Final = "IRRoundTripTrace@1"
IR_PROOF_TRACE_INTERFACE: Final = "IRProofTrace@1"
IR_TACTIC_TRACE_INTERFACE: Final = "IRTacticTrace@1"
IR_POSITIVE_PAIR_INTERFACE: Final = "IRPositivePair@1"
IR_HARD_NEGATIVE_INTERFACE: Final = "IRHardNegative@1"
IR_TRAINING_EXAMPLE_INTERFACE: Final = "IRTrainingExample@1"

LINEAGE_BINDING_SCHEMA_VERSION: Final = "ir-training-lineage/v1"
STATEMENT_BINDING_SCHEMA_VERSION: Final = "ir-statement-binding/v1"
TOOL_BINDING_SCHEMA_VERSION: Final = "ir-tool-binding/v1"
LABEL_EVIDENCE_SCHEMA_VERSION: Final = "ir-label-evidence/v1"
TRACE_REFERENCE_SCHEMA_VERSION: Final = "ir-trace-reference/v1"
TACTIC_STEP_SCHEMA_VERSION: Final = "ir-tactic-step/v1"

IR_COMPILER_TRACE_SCHEMA_VERSION: Final = "ir-compiler-trace/v1"
IR_DECOMPILER_TRACE_SCHEMA_VERSION: Final = "ir-decompiler-trace/v1"
IR_TRANSLATION_TRACE_SCHEMA_VERSION: Final = "ir-translation-trace/v1"
IR_ROUND_TRIP_TRACE_SCHEMA_VERSION: Final = "ir-round-trip-trace/v1"
IR_PROOF_TRACE_SCHEMA_VERSION: Final = "ir-proof-trace/v1"
IR_TACTIC_TRACE_SCHEMA_VERSION: Final = "ir-tactic-trace/v1"
IR_POSITIVE_PAIR_SCHEMA_VERSION: Final = "ir-positive-pair/v1"
IR_HARD_NEGATIVE_SCHEMA_VERSION: Final = "ir-hard-negative/v1"
IR_TRAINING_EXAMPLE_SCHEMA_VERSION: Final = "ir-training-example/v1"

TRAINING_CONTRACT_IDENTITY_DOMAIN: Final = "ir.training-contract"
MAX_COLLECTION_ITEMS: Final = 4_096
MAX_TEXT_CHARS: Final = 65_536

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")
_DIGEST_RE = re.compile(r"^(?:sha256:)?([0-9a-f]{64})$")
_CID_RE = re.compile(r"^b[a-z2-7]{20,}$")
_JSON_POINTER_RE = re.compile(r"^(?:/(?:[^~/]|~[01])*)+$")


class TrainingContractValidationError(FormalizationValidationError):
    """Raised when a training or trace contract fails closed."""


# ---------------------------------------------------------------------------
# Closed vocabularies
# ---------------------------------------------------------------------------


class LogicFamily(str, Enum):
    UNSPECIFIED = "unspecified"
    PROPOSITIONAL = "propositional"
    FIRST_ORDER = "first_order"
    HIGHER_ORDER = "higher_order"
    MODAL = "modal"
    DEONTIC = "deontic"
    DATALOG = "datalog"
    TEMPORAL = "temporal"
    HOARE = "hoare"
    SMT = "smt"
    THREAT_MODEL = "threat_model"
    POLICY = "policy"
    INTENT = "intent"
    LINEAR = "linear"
    SEPARATION = "separation"


class RepresentationKind(str, Enum):
    SOURCE_TEXT = "source_text"
    CONTROLLED_NATURAL_LANGUAGE = "controlled_natural_language"
    TYPED_SYNTAX = "typed_syntax"
    CANONICAL_IR = "canonical_ir"
    DOMAIN_LOGIC_SLICE = "domain_logic_slice"
    LOGIC_FAMILY = "logic_family"
    PROVER_SYNTAX = "prover_syntax"
    PROOF_STATE = "proof_state"


class SemanticRelationship(str, Enum):
    UNKNOWN = "unknown"
    EXACT = "exact"
    ALPHA_EQUIVALENT = "alpha_equivalent"
    CANONICAL_EQUIVALENT = "canonical_equivalent"
    LOGICALLY_EQUIVALENT = "logically_equivalent"
    EQUISATISFIABLE = "equisatisfiable"
    PROOF_EQUIVALENT = "proof_equivalent"
    TRANSLATION_EQUIVALENT = "translation_equivalent"
    PARAPHRASE = "paraphrase"
    ENTAILS = "entails"
    NOT_ENTAILED = "not_entailed"
    CONTRADICTS = "contradicts"
    NON_EQUIVALENT = "non_equivalent"
    MUTATION_OF = "mutation_of"


class PreservationClass(str, Enum):
    UNKNOWN = "unknown"
    LOSSLESS = "lossless"
    SYNTACTIC = "syntactic"
    STRUCTURAL = "structural"
    SEMANTIC = "semantic"
    PROOF = "proof"
    EQUISATISFIABLE = "equisatisfiable"
    OVER_APPROXIMATION = "over_approximation"
    UNDER_APPROXIMATION = "under_approximation"
    HEURISTIC = "heuristic"
    UNSUPPORTED = "unsupported"


class StatementAuthority(str, Enum):
    """Closed provenance/semantic status for a statement, not a total order."""

    UNKNOWN = "unknown"
    MODEL_CANDIDATE = "model_candidate"
    SOURCE_ASSERTED = "source_asserted"
    DETERMINISTICALLY_DERIVED = "deterministically_derived"
    CANONICALLY_VALIDATED = "canonically_validated"
    INDEPENDENTLY_VERIFIED = "independently_verified"


class LabelAuthority(str, Enum):
    """Who may support one label; generation alone never establishes truth."""

    UNKNOWN = "unknown"
    MODEL_OUTPUT = "model_output"
    TOOL_CANDIDATE = "tool_candidate"
    SOURCE_DECLARATION = "source_declaration"
    HUMAN_REVIEW = "human_review"
    DETERMINISTIC_VALIDATOR = "deterministic_validator"
    CANONICAL_VALIDATOR = "canonical_validator"
    INDEPENDENT_TRANSLATION_CHECKER = "independent_translation_checker"
    INDEPENDENT_SEMANTIC_CHECKER = "independent_semantic_checker"
    INDEPENDENT_PROOF_CHECKER = "independent_proof_checker"
    INDEPENDENT_COUNTEREXAMPLE_CHECKER = "independent_counterexample_checker"


class EvidenceStatus(str, Enum):
    CANDIDATE = "candidate"
    VERIFIED = "verified"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class ProducerKind(str, Enum):
    GENERIC_DETERMINISTIC = "generic_deterministic"
    DETERMINISTIC_COMPILER = "deterministic_compiler"
    DETERMINISTIC_DECOMPILER = "deterministic_decompiler"
    DETERMINISTIC_TRANSLATOR = "deterministic_translator"
    MODEL = "model"
    PROVER = "prover"
    SOLVER = "solver"
    CHECKER = "checker"
    TACTICIAN = "tactician"
    HUMAN = "human"


class TraceStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARSE_ERROR = "parse_error"
    TYPE_ERROR = "type_error"
    TIMED_OUT = "timed_out"
    UNAVAILABLE = "unavailable"
    CANCELLED = "cancelled"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class ProofOutcome(str, Enum):
    PROVED = "proved"
    DISPROVED = "disproved"
    CANDIDATE = "candidate"
    UNKNOWN = "unknown"
    TIMED_OUT = "timed_out"
    UNAVAILABLE = "unavailable"
    CANCELLED = "cancelled"
    ERROR = "error"


class TacticStepOutcome(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARSE_ERROR = "parse_error"
    TYPE_ERROR = "type_error"
    UNKNOWN = "unknown"


class TacticOutcome(str, Enum):
    VERIFIED_SUCCESS = "verified_success"
    CANDIDATE_SUCCESS = "candidate_success"
    FAILED = "failed"
    PARSE_ERROR = "parse_error"
    TYPE_ERROR = "type_error"
    COUNTEREXAMPLE = "counterexample"
    TIMED_OUT = "timed_out"
    UNAVAILABLE = "unavailable"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class MutationClass(str, Enum):
    NEGATION = "negation"
    OPERATOR = "operator"
    MODALITY = "modality"
    QUANTIFIER = "quantifier"
    ARGUMENT = "argument"
    CONSTANT = "constant"
    BOUNDARY = "boundary"
    EXCEPTION = "exception"
    TEMPORAL = "temporal"
    JURISDICTION = "jurisdiction"
    PREMISE = "premise"
    CROSS_REFERENCE = "cross_reference"


class NegativeDisposition(str, Enum):
    CONFIRMED_NEGATIVE = "confirmed_negative"
    UNKNOWN = "unknown"
    QUARANTINED = "quarantined"


class ExampleKind(str, Enum):
    COMPILER = "compiler"
    DECOMPILER = "decompiler"
    TRANSLATION = "translation"
    ROUND_TRIP = "round_trip"
    PROOF = "proof"
    TACTIC = "tactic"
    POSITIVE_PAIR = "positive_pair"
    HARD_NEGATIVE = "hard_negative"


class ExampleDisposition(str, Enum):
    ADMITTED = "admitted"
    QUARANTINED = "quarantined"
    REJECTED = "rejected"


class QuarantineReason(str, Enum):
    RIGHTS_NOT_ADMITTED = "rights_not_admitted"
    NON_TRAINING_SPLIT = "non_training_split"
    UNKNOWN_LOGIC_FAMILY = "unknown_logic_family"
    UNKNOWN_RELATIONSHIP = "unknown_relationship"
    UNKNOWN_PRESERVATION = "unknown_preservation"
    UNSUPPORTED_OR_HEURISTIC = "unsupported_or_heuristic"
    TRACE_NOT_SUCCEEDED = "trace_not_succeeded"
    UNRESOLVED_LOSS = "unresolved_loss"
    UNVERIFIED_EVIDENCE = "unverified_evidence"
    MODEL_ONLY_EVIDENCE = "model_only_evidence"
    CANDIDATE_STATEMENT_AUTHORITY = "candidate_statement_authority"
    UNVERIFIED_PROOF = "unverified_proof"
    UNVERIFIED_TACTIC = "unverified_tactic"
    UNKNOWN_NEGATIVE = "unknown_negative"
    MINIMALITY_UNCHECKED = "minimality_unchecked"
    POLICY = "policy"


# ---------------------------------------------------------------------------
# Validation and identity helpers
# ---------------------------------------------------------------------------


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TrainingContractValidationError(f"{field_name} must be a mapping")
    return value


def _sequence(value: Any, field_name: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TrainingContractValidationError(f"{field_name} must be a sequence")
    if len(value) > MAX_COLLECTION_ITEMS:
        raise TrainingContractValidationError(
            f"{field_name} exceeds maximum of {MAX_COLLECTION_ITEMS} items"
        )
    return value


def _reject_unknown(value: Mapping[str, Any], allowed: frozenset[str], name: str) -> None:
    if any(not isinstance(key, str) for key in value):
        raise TrainingContractValidationError(f"{name} field names must be strings")
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise TrainingContractValidationError(f"unknown {name} field(s): {', '.join(unknown)}")
    missing = sorted(allowed - set(value))
    if missing:
        raise TrainingContractValidationError(f"missing {name} field(s): {', '.join(missing)}")


def _text(value: Any, field_name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise TrainingContractValidationError(f"{field_name} must be a string")
    if len(value) > MAX_TEXT_CHARS:
        raise TrainingContractValidationError(f"{field_name} exceeds maximum length")
    if value != value.strip():
        raise TrainingContractValidationError(f"{field_name} must be trimmed")
    if not allow_empty and not value:
        raise TrainingContractValidationError(f"{field_name} must be non-empty")
    return value


def _identifier(value: Any, field_name: str, *, allow_empty: bool = False) -> str:
    text = _text(value, field_name, allow_empty=allow_empty)
    if not text and allow_empty:
        return ""
    if not _ID_RE.fullmatch(text):
        raise TrainingContractValidationError(f"{field_name} must be a stable identifier")
    return text


def _digest(value: Any, field_name: str, *, allow_empty: bool = False) -> str:
    text = _text(value, field_name, allow_empty=allow_empty)
    if not text and allow_empty:
        return ""
    match = _DIGEST_RE.fullmatch(text)
    if match is None:
        raise TrainingContractValidationError(f"{field_name} must be a lowercase SHA-256 digest")
    return f"sha256:{match.group(1)}"


def _cid(value: Any, field_name: str) -> str:
    text = _text(value, field_name)
    if not _CID_RE.fullmatch(text):
        raise TrainingContractValidationError(f"{field_name} must be a lowercase CIDv1")
    encoded = text[1:].upper()
    encoded += "=" * ((8 - len(encoded) % 8) % 8)
    try:
        raw = base64.b32decode(encoded, casefold=False)
    except (ValueError, binascii.Error) as exc:
        raise TrainingContractValidationError(f"{field_name} must be a lowercase CIDv1") from exc
    if len(raw) != 36 or raw[:4] != bytes((0x01, 0x55, 0x12, 0x20)):
        raise TrainingContractValidationError(
            f"{field_name} must use CIDv1 raw/sha2-256 identity profile"
        )
    return text


def _enum(value: Any, enum_type: type[Enum], field_name: str) -> Any:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise TrainingContractValidationError(f"{field_name} must be one of: {allowed}") from exc


def _bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TrainingContractValidationError(f"{field_name} must be a boolean")
    return value


def _unique_identifiers(
    value: Any,
    field_name: str,
    *,
    allow_empty: bool = True,
    sort: bool = True,
) -> tuple[str, ...]:
    values = tuple(_identifier(item, field_name) for item in _sequence(value, field_name))
    if not values and not allow_empty:
        raise TrainingContractValidationError(f"{field_name} must be non-empty")
    if len(values) != len(set(values)):
        raise TrainingContractValidationError(f"{field_name} values must be unique")
    return tuple(sorted(values)) if sort else values


def _unique_texts(value: Any, field_name: str, *, sort: bool = True) -> tuple[str, ...]:
    values = tuple(_text(item, field_name) for item in _sequence(value, field_name))
    if len(values) != len(set(values)):
        raise TrainingContractValidationError(f"{field_name} values must be unique")
    return tuple(sorted(values)) if sort else values


def _reject_floats(value: Any, field_name: str) -> None:
    if isinstance(value, float):
        raise TrainingContractValidationError(
            f"{field_name} must not contain float-valued durable identity"
        )
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TrainingContractValidationError(f"{field_name} keys must be strings")
            _reject_floats(item, f"{field_name}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _reject_floats(item, f"{field_name}[{index}]")


def _frozen_map(value: Any, field_name: str) -> FrozenMap:
    if isinstance(value, FrozenMap):
        value = value.to_dict()
    payload = _mapping(value, field_name)
    _reject_floats(payload, field_name)
    try:
        return FrozenMap(payload)
    except ClaimValidationError as exc:
        raise TrainingContractValidationError(str(exc)) from exc


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in pairs:
        if key in result:
            raise TrainingContractValidationError(f"duplicate JSON object field: {key}")
        result[key] = item
    return result


def _json_load(value: str | bytes | bytearray, name: str) -> Mapping[str, Any]:
    try:
        decoded = json.loads(value, object_pairs_hook=_strict_json_object)
    except TrainingContractValidationError:
        raise
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise TrainingContractValidationError(f"{name} must be valid JSON") from exc
    return _mapping(decoded, name)


class _CanonicalRecord:
    INTERFACE: ClassVar[str]
    SCHEMA_VERSION: ClassVar[str]
    IDENTITY_SUFFIX: ClassVar[str]
    COLLECTION_SCHEMA: ClassVar[Mapping[str, str]] = {}

    def to_dict(self) -> dict[str, Any]:  # pragma: no cover - interface method
        raise NotImplementedError

    @property
    def interface(self) -> str:
        return self.INTERFACE

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.to_dict(),
            domain=f"{TRAINING_CONTRACT_IDENTITY_DOMAIN}:{self.IDENTITY_SUFFIX}",
            schema_version=self.SCHEMA_VERSION,
            collection_schema=self.COLLECTION_SCHEMA,
        )

    @property
    def digest(self) -> str:
        return self.identity.digest

    @property
    def cid(self) -> str:
        return self.identity.cid

    @property
    def record_cid(self) -> str:
        return self.cid

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
    def from_json(cls, value: str | bytes | bytearray) -> Any:
        return cls.from_dict(_json_load(value, cls.__name__))


def _normalize_subjects(
    ids: Any,
    digests: Any,
    *,
    allow_empty: bool = False,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    normalized_ids = _unique_identifiers(
        ids, "subject_statement_ids", allow_empty=allow_empty, sort=False
    )
    normalized_digests = tuple(
        _digest(item, "subject_statement_digests")
        for item in _sequence(digests, "subject_statement_digests")
    )
    if not normalized_digests and not allow_empty:
        raise TrainingContractValidationError("subject_statement_digests must be non-empty")
    if len(normalized_ids) != len(normalized_digests):
        raise TrainingContractValidationError(
            "subject statement IDs and digests must have equal lengths"
        )
    pairs = tuple(sorted(zip(normalized_ids, normalized_digests, strict=True)))
    return tuple(item[0] for item in pairs), tuple(item[1] for item in pairs)


def _statement_subject_pairs(
    *statements: StatementBinding,
) -> frozenset[tuple[str, str]]:
    return frozenset((item.statement_id, item.statement_digest) for item in statements)


def _bind_statement_to_lineage(statement: StatementBinding, lineage: LineageBinding) -> None:
    if not lineage.parent_example_id and not statement.source_record_ids:
        raise TrainingContractValidationError(
            "source-rooted statements must bind at least one source record"
        )
    if not lineage.parent_example_id and not statement.source_ref_ids:
        raise TrainingContractValidationError(
            "source-rooted statements must bind at least one source reference"
        )
    unknown_groups = set(statement.lineage_group_ids) - set(lineage.lineage_group_ids)
    unknown_records = set(statement.source_record_ids) - set(lineage.source_record_ids)
    if unknown_groups:
        raise TrainingContractValidationError(
            "statement references lineage groups outside its lineage binding: "
            + ", ".join(sorted(unknown_groups))
        )
    if unknown_records:
        raise TrainingContractValidationError(
            "statement references source records outside its lineage binding: "
            + ", ".join(sorted(unknown_records))
        )


def _validate_evidence_subjects(
    evidence: Sequence[LabelEvidence],
    statements: Sequence[StatementBinding],
    relationship: SemanticRelationship | None = None,
) -> None:
    expected_subjects = _statement_subject_pairs(*statements)
    for item in evidence:
        subjects = frozenset(
            zip(item.subject_statement_ids, item.subject_statement_digests, strict=True)
        )
        if not subjects.issubset(expected_subjects):
            raise TrainingContractValidationError(
                f"evidence {item.evidence_id!r} is bound to another statement"
            )
        if item.relationship is not SemanticRelationship.UNKNOWN:
            if relationship is None or item.relationship is not relationship:
                raise TrainingContractValidationError(
                    f"evidence {item.evidence_id!r} relationship does not match its record"
                )
            if subjects != expected_subjects:
                raise TrainingContractValidationError(
                    f"relationship evidence {item.evidence_id!r} must bind every endpoint"
                )


_ALLOWED_AUTHORITY_TRANSITIONS: Final[dict[StatementAuthority, frozenset[StatementAuthority]]] = {
    StatementAuthority.UNKNOWN: frozenset({StatementAuthority.UNKNOWN}),
    StatementAuthority.MODEL_CANDIDATE: frozenset(
        {StatementAuthority.UNKNOWN, StatementAuthority.MODEL_CANDIDATE}
    ),
    StatementAuthority.SOURCE_ASSERTED: frozenset(
        {
            StatementAuthority.UNKNOWN,
            StatementAuthority.MODEL_CANDIDATE,
            StatementAuthority.SOURCE_ASSERTED,
            StatementAuthority.DETERMINISTICALLY_DERIVED,
        }
    ),
    StatementAuthority.DETERMINISTICALLY_DERIVED: frozenset(
        {
            StatementAuthority.UNKNOWN,
            StatementAuthority.MODEL_CANDIDATE,
            StatementAuthority.DETERMINISTICALLY_DERIVED,
        }
    ),
    StatementAuthority.CANONICALLY_VALIDATED: frozenset(
        {
            StatementAuthority.UNKNOWN,
            StatementAuthority.MODEL_CANDIDATE,
            StatementAuthority.SOURCE_ASSERTED,
            StatementAuthority.DETERMINISTICALLY_DERIVED,
            StatementAuthority.CANONICALLY_VALIDATED,
        }
    ),
    StatementAuthority.INDEPENDENTLY_VERIFIED: frozenset(StatementAuthority),
}


def _forbid_authority_increase(
    source: StatementAuthority, target: StatementAuthority, record_name: str
) -> None:
    if target not in _ALLOWED_AUTHORITY_TRANSITIONS[source]:
        raise TrainingContractValidationError(
            f"{record_name} cannot increase statement authority from "
            f"{source.value} to {target.value}"
        )


_RELATION_AUTHORITIES: Final[dict[SemanticRelationship, frozenset[LabelAuthority]]] = {
    SemanticRelationship.EXACT: frozenset(
        {
            LabelAuthority.DETERMINISTIC_VALIDATOR,
            LabelAuthority.CANONICAL_VALIDATOR,
            LabelAuthority.INDEPENDENT_SEMANTIC_CHECKER,
            LabelAuthority.INDEPENDENT_PROOF_CHECKER,
        }
    ),
    SemanticRelationship.ALPHA_EQUIVALENT: frozenset(
        {
            LabelAuthority.DETERMINISTIC_VALIDATOR,
            LabelAuthority.CANONICAL_VALIDATOR,
            LabelAuthority.INDEPENDENT_SEMANTIC_CHECKER,
            LabelAuthority.INDEPENDENT_PROOF_CHECKER,
        }
    ),
    SemanticRelationship.CANONICAL_EQUIVALENT: frozenset(
        {
            LabelAuthority.CANONICAL_VALIDATOR,
            LabelAuthority.INDEPENDENT_SEMANTIC_CHECKER,
            LabelAuthority.INDEPENDENT_PROOF_CHECKER,
        }
    ),
    SemanticRelationship.LOGICALLY_EQUIVALENT: frozenset(
        {
            LabelAuthority.INDEPENDENT_SEMANTIC_CHECKER,
            LabelAuthority.INDEPENDENT_PROOF_CHECKER,
        }
    ),
    SemanticRelationship.EQUISATISFIABLE: frozenset(
        {
            LabelAuthority.INDEPENDENT_SEMANTIC_CHECKER,
            LabelAuthority.INDEPENDENT_PROOF_CHECKER,
        }
    ),
    SemanticRelationship.PROOF_EQUIVALENT: frozenset({LabelAuthority.INDEPENDENT_PROOF_CHECKER}),
    SemanticRelationship.TRANSLATION_EQUIVALENT: frozenset(
        {
            LabelAuthority.INDEPENDENT_TRANSLATION_CHECKER,
            LabelAuthority.INDEPENDENT_SEMANTIC_CHECKER,
            LabelAuthority.INDEPENDENT_PROOF_CHECKER,
        }
    ),
    SemanticRelationship.PARAPHRASE: frozenset(
        {LabelAuthority.HUMAN_REVIEW, LabelAuthority.INDEPENDENT_SEMANTIC_CHECKER}
    ),
    SemanticRelationship.ENTAILS: frozenset(
        {
            LabelAuthority.INDEPENDENT_SEMANTIC_CHECKER,
            LabelAuthority.INDEPENDENT_PROOF_CHECKER,
        }
    ),
    SemanticRelationship.NOT_ENTAILED: frozenset(
        {
            LabelAuthority.INDEPENDENT_SEMANTIC_CHECKER,
            LabelAuthority.INDEPENDENT_COUNTEREXAMPLE_CHECKER,
        }
    ),
    SemanticRelationship.CONTRADICTS: frozenset(
        {
            LabelAuthority.INDEPENDENT_SEMANTIC_CHECKER,
            LabelAuthority.INDEPENDENT_PROOF_CHECKER,
            LabelAuthority.INDEPENDENT_COUNTEREXAMPLE_CHECKER,
        }
    ),
    SemanticRelationship.NON_EQUIVALENT: frozenset(
        {
            LabelAuthority.INDEPENDENT_SEMANTIC_CHECKER,
            LabelAuthority.INDEPENDENT_PROOF_CHECKER,
            LabelAuthority.INDEPENDENT_COUNTEREXAMPLE_CHECKER,
        }
    ),
    SemanticRelationship.MUTATION_OF: frozenset(
        {
            LabelAuthority.DETERMINISTIC_VALIDATOR,
            LabelAuthority.CANONICAL_VALIDATOR,
            LabelAuthority.HUMAN_REVIEW,
        }
    ),
    SemanticRelationship.UNKNOWN: frozenset(),
}


def _has_verified_relationship_evidence(
    evidence: Sequence[LabelEvidence],
    statements: Sequence[StatementBinding],
    relationship: SemanticRelationship,
) -> bool:
    if relationship is SemanticRelationship.UNKNOWN:
        return False
    expected_subjects = _statement_subject_pairs(*statements)
    return any(
        item.status is EvidenceStatus.VERIFIED
        and item.authority in _RELATION_AUTHORITIES[relationship]
        and item.relationship is relationship
        and frozenset(zip(item.subject_statement_ids, item.subject_statement_digests, strict=True))
        == expected_subjects
        for item in evidence
    )


def _normalize_evidence(value: Any) -> tuple[LabelEvidence, ...]:
    items = tuple(
        item
        if isinstance(item, LabelEvidence)
        else LabelEvidence.from_dict(_mapping(item, "evidence"))
        for item in _sequence(value, "evidence")
    )
    ids = tuple(item.evidence_id for item in items)
    if len(ids) != len(set(ids)):
        raise TrainingContractValidationError("evidence IDs must be unique")
    return tuple(sorted(items, key=lambda item: item.evidence_id))


# ---------------------------------------------------------------------------
# Shared dependency bindings
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LineageBinding(_CanonicalRecord):
    """Exact corpus, lineage, rights, and split roots for one record."""

    INTERFACE: ClassVar[str] = LINEAGE_BINDING_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = LINEAGE_BINDING_SCHEMA_VERSION
    IDENTITY_SUFFIX: ClassVar[str] = "lineage"
    COLLECTION_SCHEMA: ClassVar[Mapping[str, str]] = {
        "/lineage_group_ids": "set-like",
        "/source_record_ids": "set-like",
    }

    corpus_manifest_id: str
    corpus_manifest_cid: str
    lineage_graph_id: str
    lineage_graph_cid: str
    split_manifest_id: str
    split_manifest_digest: str
    split_name: str
    lineage_group_ids: tuple[str, ...]
    rights_disposition: RightsDisposition
    source_record_ids: tuple[str, ...] = ()
    parent_example_id: str = ""
    parent_example_digest: str = ""
    schema_version: str = LINEAGE_BINDING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "corpus_manifest_id", _identifier(self.corpus_manifest_id, "corpus_manifest_id")
        )
        object.__setattr__(
            self, "corpus_manifest_cid", _cid(self.corpus_manifest_cid, "corpus_manifest_cid")
        )
        object.__setattr__(
            self, "lineage_graph_id", _identifier(self.lineage_graph_id, "lineage_graph_id")
        )
        object.__setattr__(
            self, "lineage_graph_cid", _cid(self.lineage_graph_cid, "lineage_graph_cid")
        )
        object.__setattr__(
            self, "split_manifest_id", _identifier(self.split_manifest_id, "split_manifest_id")
        )
        object.__setattr__(
            self,
            "split_manifest_digest",
            _digest(self.split_manifest_digest, "split_manifest_digest"),
        )
        object.__setattr__(self, "split_name", _identifier(self.split_name, "split_name"))
        object.__setattr__(
            self,
            "lineage_group_ids",
            _unique_identifiers(self.lineage_group_ids, "lineage_group_ids", allow_empty=False),
        )
        object.__setattr__(
            self,
            "source_record_ids",
            _unique_identifiers(self.source_record_ids, "source_record_ids"),
        )
        object.__setattr__(
            self,
            "rights_disposition",
            _enum(self.rights_disposition, RightsDisposition, "rights_disposition"),
        )
        object.__setattr__(
            self,
            "parent_example_id",
            _identifier(self.parent_example_id, "parent_example_id", allow_empty=True),
        )
        object.__setattr__(
            self,
            "parent_example_digest",
            _digest(self.parent_example_digest, "parent_example_digest", allow_empty=True),
        )
        object.__setattr__(self, "schema_version", _text(self.schema_version, "schema_version"))
        if self.schema_version != self.SCHEMA_VERSION:
            raise TrainingContractValidationError(
                f"unsupported lineage binding schema: {self.schema_version!r}"
            )
        if bool(self.parent_example_id) != bool(self.parent_example_digest):
            raise TrainingContractValidationError(
                "parent_example_id and parent_example_digest must be provided together"
            )
        if not self.source_record_ids and not self.parent_example_id:
            raise TrainingContractValidationError(
                "lineage binding requires source_record_ids or a bound parent example"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus_manifest_cid": self.corpus_manifest_cid,
            "corpus_manifest_id": self.corpus_manifest_id,
            "lineage_graph_cid": self.lineage_graph_cid,
            "lineage_graph_id": self.lineage_graph_id,
            "lineage_group_ids": list(self.lineage_group_ids),
            "parent_example_digest": self.parent_example_digest,
            "parent_example_id": self.parent_example_id,
            "rights_disposition": self.rights_disposition.value,
            "schema_version": self.schema_version,
            "source_record_ids": list(self.source_record_ids),
            "split_manifest_digest": self.split_manifest_digest,
            "split_manifest_id": self.split_manifest_id,
            "split_name": self.split_name,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> LineageBinding:
        value = _mapping(value, "lineage binding")
        _reject_unknown(
            value,
            frozenset(
                {
                    "corpus_manifest_cid",
                    "corpus_manifest_id",
                    "lineage_graph_cid",
                    "lineage_graph_id",
                    "lineage_group_ids",
                    "parent_example_digest",
                    "parent_example_id",
                    "rights_disposition",
                    "schema_version",
                    "source_record_ids",
                    "split_manifest_digest",
                    "split_manifest_id",
                    "split_name",
                }
            ),
            "lineage binding",
        )
        return cls(
            corpus_manifest_id=value.get("corpus_manifest_id", ""),
            corpus_manifest_cid=value.get("corpus_manifest_cid", ""),
            lineage_graph_id=value.get("lineage_graph_id", ""),
            lineage_graph_cid=value.get("lineage_graph_cid", ""),
            split_manifest_id=value.get("split_manifest_id", ""),
            split_manifest_digest=value.get("split_manifest_digest", ""),
            split_name=value.get("split_name", ""),
            lineage_group_ids=tuple(
                _sequence(value.get("lineage_group_ids", ()), "lineage_group_ids")
            ),
            rights_disposition=value.get("rights_disposition", ""),
            source_record_ids=tuple(
                _sequence(value.get("source_record_ids", ()), "source_record_ids")
            ),
            parent_example_id=value.get("parent_example_id", ""),
            parent_example_digest=value.get("parent_example_digest", ""),
            schema_version=value.get("schema_version", LINEAGE_BINDING_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class StatementBinding(_CanonicalRecord):
    """One statement plus the exact artifact and source lineage it belongs to."""

    INTERFACE: ClassVar[str] = STATEMENT_BINDING_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = STATEMENT_BINDING_SCHEMA_VERSION
    IDENTITY_SUFFIX: ClassVar[str] = "statement"
    COLLECTION_SCHEMA: ClassVar[Mapping[str, str]] = {
        "/lineage_group_ids": "set-like",
        "/source_record_ids": "set-like",
        "/source_ref_ids": "set-like",
    }

    statement_id: str
    statement_digest: str
    representation: RepresentationKind
    logic_family: LogicFamily
    artifact_id: str
    artifact_digest: str
    lineage_group_ids: tuple[str, ...]
    source_record_ids: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()
    schema_version: str = STATEMENT_BINDING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "statement_id", _identifier(self.statement_id, "statement_id"))
        object.__setattr__(
            self, "statement_digest", _digest(self.statement_digest, "statement_digest")
        )
        object.__setattr__(
            self, "representation", _enum(self.representation, RepresentationKind, "representation")
        )
        object.__setattr__(
            self, "logic_family", _enum(self.logic_family, LogicFamily, "logic_family")
        )
        object.__setattr__(self, "artifact_id", _identifier(self.artifact_id, "artifact_id"))
        object.__setattr__(
            self, "artifact_digest", _digest(self.artifact_digest, "artifact_digest")
        )
        object.__setattr__(
            self,
            "lineage_group_ids",
            _unique_identifiers(self.lineage_group_ids, "lineage_group_ids", allow_empty=False),
        )
        object.__setattr__(
            self,
            "source_record_ids",
            _unique_identifiers(self.source_record_ids, "source_record_ids"),
        )
        object.__setattr__(
            self, "source_ref_ids", _unique_identifiers(self.source_ref_ids, "source_ref_ids")
        )
        object.__setattr__(self, "schema_version", _text(self.schema_version, "schema_version"))
        if self.schema_version != self.SCHEMA_VERSION:
            raise TrainingContractValidationError(
                f"unsupported statement binding schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_digest": self.artifact_digest,
            "artifact_id": self.artifact_id,
            "lineage_group_ids": list(self.lineage_group_ids),
            "logic_family": self.logic_family.value,
            "representation": self.representation.value,
            "schema_version": self.schema_version,
            "source_record_ids": list(self.source_record_ids),
            "source_ref_ids": list(self.source_ref_ids),
            "statement_digest": self.statement_digest,
            "statement_id": self.statement_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> StatementBinding:
        value = _mapping(value, "statement binding")
        _reject_unknown(
            value,
            frozenset(
                {
                    "artifact_digest",
                    "artifact_id",
                    "lineage_group_ids",
                    "logic_family",
                    "representation",
                    "schema_version",
                    "source_record_ids",
                    "source_ref_ids",
                    "statement_digest",
                    "statement_id",
                }
            ),
            "statement binding",
        )
        return cls(
            statement_id=value.get("statement_id", ""),
            statement_digest=value.get("statement_digest", ""),
            representation=value.get("representation", ""),
            logic_family=value.get("logic_family", ""),
            artifact_id=value.get("artifact_id", ""),
            artifact_digest=value.get("artifact_digest", ""),
            lineage_group_ids=tuple(
                _sequence(value.get("lineage_group_ids", ()), "lineage_group_ids")
            ),
            source_record_ids=tuple(
                _sequence(value.get("source_record_ids", ()), "source_record_ids")
            ),
            source_ref_ids=tuple(_sequence(value.get("source_ref_ids", ()), "source_ref_ids")),
            schema_version=value.get("schema_version", STATEMENT_BINDING_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class ToolBinding(_CanonicalRecord):
    """Exact producer/checker implementation, config, and optional model revision."""

    INTERFACE: ClassVar[str] = TOOL_BINDING_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = TOOL_BINDING_SCHEMA_VERSION
    IDENTITY_SUFFIX: ClassVar[str] = "tool"

    tool_id: str
    tool_version: str
    producer_kind: ProducerKind
    config_digest: str
    implementation_digest: str
    model_checkpoint_id: str = ""
    model_checkpoint_digest: str = ""
    schema_version: str = TOOL_BINDING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_id", _identifier(self.tool_id, "tool_id"))
        object.__setattr__(self, "tool_version", _identifier(self.tool_version, "tool_version"))
        object.__setattr__(
            self, "producer_kind", _enum(self.producer_kind, ProducerKind, "producer_kind")
        )
        object.__setattr__(self, "config_digest", _digest(self.config_digest, "config_digest"))
        object.__setattr__(
            self,
            "implementation_digest",
            _digest(self.implementation_digest, "implementation_digest"),
        )
        object.__setattr__(
            self,
            "model_checkpoint_id",
            _identifier(self.model_checkpoint_id, "model_checkpoint_id", allow_empty=True),
        )
        object.__setattr__(
            self,
            "model_checkpoint_digest",
            _digest(self.model_checkpoint_digest, "model_checkpoint_digest", allow_empty=True),
        )
        object.__setattr__(self, "schema_version", _text(self.schema_version, "schema_version"))
        if self.schema_version != self.SCHEMA_VERSION:
            raise TrainingContractValidationError(
                f"unsupported tool binding schema: {self.schema_version!r}"
            )
        if bool(self.model_checkpoint_id) != bool(self.model_checkpoint_digest):
            raise TrainingContractValidationError(
                "model_checkpoint_id and model_checkpoint_digest must be provided together"
            )
        if self.producer_kind is ProducerKind.MODEL and not self.model_checkpoint_id:
            raise TrainingContractValidationError("model tools must bind a model checkpoint")

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_digest": self.config_digest,
            "implementation_digest": self.implementation_digest,
            "model_checkpoint_digest": self.model_checkpoint_digest,
            "model_checkpoint_id": self.model_checkpoint_id,
            "producer_kind": self.producer_kind.value,
            "schema_version": self.schema_version,
            "tool_id": self.tool_id,
            "tool_version": self.tool_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ToolBinding:
        value = _mapping(value, "tool binding")
        _reject_unknown(
            value,
            frozenset(
                {
                    "config_digest",
                    "implementation_digest",
                    "model_checkpoint_digest",
                    "model_checkpoint_id",
                    "producer_kind",
                    "schema_version",
                    "tool_id",
                    "tool_version",
                }
            ),
            "tool binding",
        )
        return cls(
            tool_id=value.get("tool_id", ""),
            tool_version=value.get("tool_version", ""),
            producer_kind=value.get("producer_kind", ""),
            config_digest=value.get("config_digest", ""),
            implementation_digest=value.get("implementation_digest", ""),
            model_checkpoint_id=value.get("model_checkpoint_id", ""),
            model_checkpoint_digest=value.get("model_checkpoint_digest", ""),
            schema_version=value.get("schema_version", TOOL_BINDING_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class LabelEvidence(_CanonicalRecord):
    """Content-bound evidence for one statement or relationship label."""

    INTERFACE: ClassVar[str] = LABEL_EVIDENCE_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = LABEL_EVIDENCE_SCHEMA_VERSION
    IDENTITY_SUFFIX: ClassVar[str] = "label-evidence"
    COLLECTION_SCHEMA: ClassVar[Mapping[str, str]] = {
        "/subject_statement_ids": "ordered",
        "/subject_statement_digests": "ordered",
    }

    evidence_id: str
    evidence_digest: str
    authority: LabelAuthority
    status: EvidenceStatus
    subject_statement_ids: tuple[str, ...]
    subject_statement_digests: tuple[str, ...]
    producer_id: str
    producer_version: str
    independent: bool
    relationship: SemanticRelationship = SemanticRelationship.UNKNOWN
    result_authority: AuthorityKind | None = None
    schema_version: str = LABEL_EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_id", _identifier(self.evidence_id, "evidence_id"))
        object.__setattr__(
            self, "evidence_digest", _digest(self.evidence_digest, "evidence_digest")
        )
        object.__setattr__(self, "authority", _enum(self.authority, LabelAuthority, "authority"))
        object.__setattr__(self, "status", _enum(self.status, EvidenceStatus, "status"))
        ids, digests = _normalize_subjects(
            self.subject_statement_ids, self.subject_statement_digests
        )
        object.__setattr__(self, "subject_statement_ids", ids)
        object.__setattr__(self, "subject_statement_digests", digests)
        object.__setattr__(self, "producer_id", _identifier(self.producer_id, "producer_id"))
        object.__setattr__(
            self, "producer_version", _identifier(self.producer_version, "producer_version")
        )
        object.__setattr__(self, "independent", _bool(self.independent, "independent"))
        object.__setattr__(
            self, "relationship", _enum(self.relationship, SemanticRelationship, "relationship")
        )
        if self.result_authority in (None, ""):
            object.__setattr__(self, "result_authority", None)
        else:
            object.__setattr__(
                self,
                "result_authority",
                _enum(self.result_authority, AuthorityKind, "result_authority"),
            )
        object.__setattr__(self, "schema_version", _text(self.schema_version, "schema_version"))
        if self.schema_version != self.SCHEMA_VERSION:
            raise TrainingContractValidationError(
                f"unsupported label evidence schema: {self.schema_version!r}"
            )
        candidate_authorities = {LabelAuthority.MODEL_OUTPUT, LabelAuthority.TOOL_CANDIDATE}
        if self.authority in candidate_authorities and self.status is EvidenceStatus.VERIFIED:
            raise TrainingContractValidationError(
                "model/tool candidate evidence cannot be verified authority"
            )
        independent_authorities = {
            LabelAuthority.INDEPENDENT_TRANSLATION_CHECKER,
            LabelAuthority.INDEPENDENT_SEMANTIC_CHECKER,
            LabelAuthority.INDEPENDENT_PROOF_CHECKER,
            LabelAuthority.INDEPENDENT_COUNTEREXAMPLE_CHECKER,
        }
        if self.authority in independent_authorities and not self.independent:
            raise TrainingContractValidationError(
                f"{self.authority.value} evidence must be independently checked"
            )
        if self.status is EvidenceStatus.VERIFIED and self.authority is LabelAuthority.UNKNOWN:
            raise TrainingContractValidationError("unknown authority cannot verify a label")
        allowed_result_authorities = {
            LabelAuthority.INDEPENDENT_PROOF_CHECKER: frozenset({AuthorityKind.THEOREM_PROOF}),
            LabelAuthority.INDEPENDENT_SEMANTIC_CHECKER: frozenset(
                {AuthorityKind.THEOREM_PROOF, AuthorityKind.SATISFIABILITY}
            ),
            LabelAuthority.INDEPENDENT_COUNTEREXAMPLE_CHECKER: frozenset(
                {AuthorityKind.SATISFIABILITY}
            ),
        }.get(self.authority, frozenset())
        if (
            self.authority is LabelAuthority.INDEPENDENT_PROOF_CHECKER
            and self.result_authority is None
        ):
            raise TrainingContractValidationError(
                "independent proof evidence requires theorem_proof result authority"
            )
        if (
            self.result_authority is not None
            and self.result_authority not in allowed_result_authorities
        ):
            raise TrainingContractValidationError(
                f"{self.result_authority.value} result authority cannot substitute for "
                f"{self.authority.value} label authority"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority.value,
            "evidence_digest": self.evidence_digest,
            "evidence_id": self.evidence_id,
            "independent": self.independent,
            "producer_id": self.producer_id,
            "producer_version": self.producer_version,
            "relationship": self.relationship.value,
            "result_authority": self.result_authority.value if self.result_authority else "",
            "schema_version": self.schema_version,
            "status": self.status.value,
            "subject_statement_digests": list(self.subject_statement_digests),
            "subject_statement_ids": list(self.subject_statement_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> LabelEvidence:
        value = _mapping(value, "label evidence")
        _reject_unknown(
            value,
            frozenset(
                {
                    "authority",
                    "evidence_digest",
                    "evidence_id",
                    "independent",
                    "producer_id",
                    "producer_version",
                    "relationship",
                    "result_authority",
                    "schema_version",
                    "status",
                    "subject_statement_digests",
                    "subject_statement_ids",
                }
            ),
            "label evidence",
        )
        return cls(
            evidence_id=value.get("evidence_id", ""),
            evidence_digest=value.get("evidence_digest", ""),
            authority=value.get("authority", ""),
            status=value.get("status", ""),
            subject_statement_ids=tuple(
                _sequence(value.get("subject_statement_ids", ()), "subject_statement_ids")
            ),
            subject_statement_digests=tuple(
                _sequence(value.get("subject_statement_digests", ()), "subject_statement_digests")
            ),
            producer_id=value.get("producer_id", ""),
            producer_version=value.get("producer_version", ""),
            independent=value.get("independent", False),
            relationship=value.get("relationship", SemanticRelationship.UNKNOWN.value),
            result_authority=value.get("result_authority", None),
            schema_version=value.get("schema_version", LABEL_EVIDENCE_SCHEMA_VERSION),
        )
