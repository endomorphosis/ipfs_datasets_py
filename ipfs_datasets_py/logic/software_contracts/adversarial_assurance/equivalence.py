"""Bounded equivalent-mutant analysis (AAE-025).

Implements ``assess_mutation_equivalence@1`` from plan §9 and AAE-G040.

The analyzer composes AST comparison, normalized IR, constant propagation,
reachability, available symbolic execution, restricted SMT, bounded public
behavior, and human-review escalation. Difficulty to kill and a candidate's
``likely_equivalent`` flag are never treated as evidence. ``unknown`` never
becomes ``equivalent`` automatically. Missing observation capability fails
closed.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from enum import Enum
import operator
from types import MappingProxyType
import re
import unicodedata
from typing import Any, ClassVar, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_structured,
    validate_cid,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.common import (
    AssuranceArtifactHeader,
    AssuranceBaseError,
    GeneratorIdentity,
    VersionBinding,
    reject_private_model_authority_and_host_fallbacks,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.execution_contracts import (
    EquivalenceAssessmentStatus,
    EquivalenceMethod,
    ExecutionContractError,
    MutationEquivalenceAssessment,
    equivalence_assessment_statuses,
    equivalence_methods,
)

# ---------------------------------------------------------------------------
# Schema / interface constants (normative)
# ---------------------------------------------------------------------------

ASSESS_MUTATION_EQUIVALENCE_INTERFACE: Final[str] = "assess_mutation_equivalence@1"
EQUIVALENCE_SUBJECT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-equivalence-subject@1"
)
EQUIVALENCE_SUBJECT_INTERFACE: Final[str] = "EquivalenceSubject@1"
METHOD_EVIDENCE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-equivalence-method-evidence@1"
)

GENERATOR_ID: Final[str] = "equivalence"
GENERATOR_VERSION: Final[str] = "1.0.0"

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_SOURCE_CHARS: Final[int] = 65_536
MAX_LIST: Final[int] = 1_024
MAX_BEHAVIOR_PAIRS: Final[int] = 256

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_.:/+-]{0,127}$")


class EquivalenceAnalysisError(AssuranceBaseError):
    """Raised when equivalence analysis inputs fail closed."""


class MethodVerdict(str, Enum):
    """Closed per-method verdict used only inside this analyzer."""

    EQUIVALENT = "equivalent"
    NOT_EQUIVALENT = "not_equivalent"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, empty: bool = False, maximum: int = MAX_TEXT_CHARS) -> str:
    if type(value) is not str or (not empty and not value):
        raise EquivalenceAnalysisError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise EquivalenceAnalysisError(
            f"{name} must be NFC-normalized and free of leading/trailing whitespace"
        )
    if len(value) > maximum:
        raise EquivalenceAnalysisError(f"{name} exceeds maximum length")
    reject_private_model_authority_and_host_fallbacks({name: value}, path=name)
    return value


def _optional_text(
    value: Any, name: str, *, maximum: int = MAX_TEXT_CHARS
) -> str | None:
    if value is None:
        return None
    return _text(value, name, maximum=maximum)


def _source(value: Any, name: str) -> str:
    return _text(value, name, maximum=MAX_SOURCE_CHARS)


def _optional_source(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _source(value, name)


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise EquivalenceAnalysisError(f"{name} must be a boolean")
    return value


def _token(value: Any, name: str) -> str:
    text = _text(value, name)
    if _TOKEN_RE.fullmatch(text) is None:
        raise EquivalenceAnalysisError(
            f"{name} must be a lowercase token matching {_TOKEN_RE.pattern}"
        )
    return text


def _cid(value: Any, name: str) -> str:
    text = _text(value, name)
    try:
        validate_cid(text)
    except Exception as exc:  # pragma: no cover - validate_cid raises ValueError
        raise EquivalenceAnalysisError(f"{name} must be a valid CIDv1") from exc
    return text


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    if isinstance(value, enum_type):
        return value.value
    if type(value) is str:
        try:
            return enum_type(value).value
        except ValueError as exc:
            raise EquivalenceAnalysisError(
                f"{name}={value!r} is not an admitted {enum_type.__name__}"
            ) from exc
    raise EquivalenceAnalysisError(f"{name} must be {enum_type.__name__} or string")


def _freeze_structured(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_structured(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_structured(item) for item in value)
    return value


def _thaw_structured(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_structured(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_structured(item) for item in value]
    return value


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise EquivalenceAnalysisError(f"{name} must be a mapping")
    extra = set(data) - fields
    if extra:
        raise EquivalenceAnalysisError(
            f"{name} contains unknown fields: {sorted(extra)}"
        )
    missing = fields - set(data)
    if missing:
        raise EquivalenceAnalysisError(f"{name} missing fields: {sorted(missing)}")
    return dict(data)


def _header(value: Any, name: str = "header") -> AssuranceArtifactHeader:
    if isinstance(value, AssuranceArtifactHeader):
        return value
    if isinstance(value, Mapping):
        try:
            return AssuranceArtifactHeader.from_dict(value)
        except AssuranceBaseError as exc:
            raise EquivalenceAnalysisError(str(exc)) from exc
    raise EquivalenceAnalysisError(f"{name} must be AssuranceArtifactHeader or mapping")


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise EquivalenceAnalysisError(f"{name} must be a mapping")
    reject_private_model_authority_and_host_fallbacks(dict(value), path=name)
    return MappingProxyType(_freeze_structured(dict(value)))


# ---------------------------------------------------------------------------
# Bounded behavior pair
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BoundedBehaviorPair:
    """One public input/output observation over a bounded domain."""

    input_cid: str
    original_output_cid: str
    mutant_output_cid: str

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"input_cid", "original_output_cid", "mutant_output_cid"}
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "input_cid", _cid(self.input_cid, "input_cid"))
        object.__setattr__(
            self,
            "original_output_cid",
            _cid(self.original_output_cid, "original_output_cid"),
        )
        object.__setattr__(
            self,
            "mutant_output_cid",
            _cid(self.mutant_output_cid, "mutant_output_cid"),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "input_cid": self.input_cid,
            "original_output_cid": self.original_output_cid,
            "mutant_output_cid": self.mutant_output_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BoundedBehaviorPair":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        return cls(
            input_cid=payload["input_cid"],
            original_output_cid=payload["original_output_cid"],
            mutant_output_cid=payload["mutant_output_cid"],
        )


def _behavior_pairs(value: Any, name: str) -> tuple[BoundedBehaviorPair, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise EquivalenceAnalysisError(f"{name} must be a list")
    if len(value) > MAX_BEHAVIOR_PAIRS:
        raise EquivalenceAnalysisError(f"{name} exceeds maximum length")
    pairs: list[BoundedBehaviorPair] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        if isinstance(item, BoundedBehaviorPair):
            pair = item
        elif isinstance(item, Mapping):
            pair = BoundedBehaviorPair.from_dict(item)
        else:
            raise EquivalenceAnalysisError(
                f"{name}[{index}] must be BoundedBehaviorPair or mapping"
            )
        if pair.input_cid in seen:
            raise EquivalenceAnalysisError(
                f"{name} contains duplicate input_cid {pair.input_cid}"
            )
        seen.add(pair.input_cid)
        pairs.append(pair)
    return tuple(pairs)


# ---------------------------------------------------------------------------
# Subject
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EquivalenceSubject:
    """Closed observation record for bounded equivalence analysis.

    Callers supply source texts and already-collected observations. This
    module does not invent SMT, symbolic, reachability, or behavior facts.
    ``observation_complete=false`` fails closed. ``likely_equivalent`` and
    ``difficulty_to_kill`` are accepted so they can be ignored as evidence.
    """

    subject_id: str
    candidate_id: str
    candidate_cid: str
    original_source: str
    mutant_source: str
    observation_complete: bool
    subject_cid: str
    original_normalized_ir: str | None = None
    mutant_normalized_ir: str | None = None
    original_reachable_fragment: str | None = None
    mutant_reachable_fragment: str | None = None
    reachability_observed: bool = False
    symbolic_capability: bool = False
    symbolic_verdict: str | None = None
    smt_capability: bool = False
    smt_verdict: str | None = None
    bounded_behavior: Sequence[BoundedBehaviorPair] = ()
    bounded_behavior_observed: bool = False
    high_value: bool = False
    likely_equivalent: bool = False
    difficulty_to_kill: bool = False
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "subject_id",
            "candidate_id",
            "candidate_cid",
            "original_source",
            "mutant_source",
            "original_normalized_ir",
            "mutant_normalized_ir",
            "original_reachable_fragment",
            "mutant_reachable_fragment",
            "reachability_observed",
            "symbolic_capability",
            "symbolic_verdict",
            "smt_capability",
            "smt_verdict",
            "bounded_behavior",
            "bounded_behavior_observed",
            "high_value",
            "likely_equivalent",
            "difficulty_to_kill",
            "observation_complete",
            "subject_cid",
            "notes",
            "metadata",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject_id", _token(self.subject_id, "subject_id"))
        object.__setattr__(
            self, "candidate_id", _token(self.candidate_id, "candidate_id")
        )
        object.__setattr__(
            self, "candidate_cid", _cid(self.candidate_cid, "candidate_cid")
        )
        object.__setattr__(
            self, "original_source", _source(self.original_source, "original_source")
        )
        object.__setattr__(
            self, "mutant_source", _source(self.mutant_source, "mutant_source")
        )
        object.__setattr__(
            self,
            "original_normalized_ir",
            _optional_source(self.original_normalized_ir, "original_normalized_ir"),
        )
        object.__setattr__(
            self,
            "mutant_normalized_ir",
            _optional_source(self.mutant_normalized_ir, "mutant_normalized_ir"),
        )
        object.__setattr__(
            self,
            "original_reachable_fragment",
            _optional_source(
                self.original_reachable_fragment, "original_reachable_fragment"
            ),
        )
        object.__setattr__(
            self,
            "mutant_reachable_fragment",
            _optional_source(
                self.mutant_reachable_fragment, "mutant_reachable_fragment"
            ),
        )
        object.__setattr__(
            self,
            "reachability_observed",
            _bool(self.reachability_observed, "reachability_observed"),
        )
        object.__setattr__(
            self,
            "symbolic_capability",
            _bool(self.symbolic_capability, "symbolic_capability"),
        )
        object.__setattr__(
            self,
            "symbolic_verdict",
            _optional_verdict(self.symbolic_verdict, "symbolic_verdict"),
        )
        object.__setattr__(
            self, "smt_capability", _bool(self.smt_capability, "smt_capability")
        )
        object.__setattr__(
            self, "smt_verdict", _optional_verdict(self.smt_verdict, "smt_verdict")
        )
        object.__setattr__(
            self, "bounded_behavior", _behavior_pairs(self.bounded_behavior, "bounded_behavior")
        )
        object.__setattr__(
            self,
            "bounded_behavior_observed",
            _bool(self.bounded_behavior_observed, "bounded_behavior_observed"),
        )
        if self.bounded_behavior_observed and not self.bounded_behavior:
            raise EquivalenceAnalysisError(
                "bounded_behavior_observed requires at least one behavior pair"
            )
        if self.reachability_observed and (
            self.original_reachable_fragment is None
            or self.mutant_reachable_fragment is None
        ):
            raise EquivalenceAnalysisError(
                "reachability_observed requires both reachable fragments"
            )
        if self.symbolic_capability and self.symbolic_verdict is None:
            raise EquivalenceAnalysisError(
                "symbolic_capability requires a symbolic_verdict"
            )
        if self.smt_capability and self.smt_verdict is None:
            raise EquivalenceAnalysisError("smt_capability requires an smt_verdict")
        object.__setattr__(self, "high_value", _bool(self.high_value, "high_value"))
        object.__setattr__(
            self, "likely_equivalent", _bool(self.likely_equivalent, "likely_equivalent")
        )
        object.__setattr__(
            self, "difficulty_to_kill", _bool(self.difficulty_to_kill, "difficulty_to_kill")
        )
        object.__setattr__(
            self,
            "observation_complete",
            _bool(self.observation_complete, "observation_complete"),
        )
        object.__setattr__(self, "subject_cid", _cid(self.subject_cid, "subject_cid"))
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": EQUIVALENCE_SUBJECT_SCHEMA,
            "interface_id": EQUIVALENCE_SUBJECT_INTERFACE,
            "subject_id": self.subject_id,
            "candidate_id": self.candidate_id,
            "candidate_cid": self.candidate_cid,
            "original_source": self.original_source,
            "mutant_source": self.mutant_source,
            "original_normalized_ir": self.original_normalized_ir,
            "mutant_normalized_ir": self.mutant_normalized_ir,
            "original_reachable_fragment": self.original_reachable_fragment,
            "mutant_reachable_fragment": self.mutant_reachable_fragment,
            "reachability_observed": self.reachability_observed,
            "symbolic_capability": self.symbolic_capability,
            "symbolic_verdict": self.symbolic_verdict,
            "smt_capability": self.smt_capability,
            "smt_verdict": self.smt_verdict,
            "bounded_behavior": [item.to_dict() for item in self.bounded_behavior],
            "bounded_behavior_observed": self.bounded_behavior_observed,
            "high_value": self.high_value,
            "likely_equivalent": self.likely_equivalent,
            "difficulty_to_kill": self.difficulty_to_kill,
            "observation_complete": self.observation_complete,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def observation_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["subject_cid"] = self.subject_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EquivalenceSubject":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        if payload.pop("schema") != EQUIVALENCE_SUBJECT_SCHEMA:
            raise EquivalenceAnalysisError("unsupported EquivalenceSubject schema")
        if payload.pop("interface_id") != EQUIVALENCE_SUBJECT_INTERFACE:
            raise EquivalenceAnalysisError("unsupported EquivalenceSubject interface")
        return cls(
            subject_id=payload["subject_id"],
            candidate_id=payload["candidate_id"],
            candidate_cid=payload["candidate_cid"],
            original_source=payload["original_source"],
            mutant_source=payload["mutant_source"],
            original_normalized_ir=payload["original_normalized_ir"],
            mutant_normalized_ir=payload["mutant_normalized_ir"],
            original_reachable_fragment=payload["original_reachable_fragment"],
            mutant_reachable_fragment=payload["mutant_reachable_fragment"],
            reachability_observed=payload["reachability_observed"],
            symbolic_capability=payload["symbolic_capability"],
            symbolic_verdict=payload["symbolic_verdict"],
            smt_capability=payload["smt_capability"],
            smt_verdict=payload["smt_verdict"],
            bounded_behavior=payload["bounded_behavior"],
            bounded_behavior_observed=payload["bounded_behavior_observed"],
            high_value=payload["high_value"],
            likely_equivalent=payload["likely_equivalent"],
            difficulty_to_kill=payload["difficulty_to_kill"],
            observation_complete=payload["observation_complete"],
            subject_cid=payload["subject_cid"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )


def _optional_verdict(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _enum(value, MethodVerdict, name)


def _normalize_subject(value: Any) -> EquivalenceSubject:
    if isinstance(value, EquivalenceSubject):
        return value
    if isinstance(value, Mapping):
        return EquivalenceSubject.from_dict(value)
    raise EquivalenceAnalysisError("subject must be EquivalenceSubject or mapping")


# ---------------------------------------------------------------------------
# AST / IR helpers
# ---------------------------------------------------------------------------


_BINOPS: Final[dict[type[ast.AST], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.FloorDiv: operator.floordiv,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.LShift: operator.lshift,
    ast.RShift: operator.rshift,
    ast.BitOr: operator.or_,
    ast.BitXor: operator.xor,
    ast.BitAnd: operator.and_,
}
_UNARYOPS: Final[dict[type[ast.AST], Any]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Not: operator.not_,
    ast.Invert: operator.invert,
}


class _ConstantFolder(ast.NodeTransformer):
    """Fold literal constant expressions. Unknown nodes are left in place."""

    def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
        node = self.generic_visit(node)
        fn = _BINOPS.get(type(node.op))
        if (
            fn is not None
            and isinstance(node.left, ast.Constant)
            and isinstance(node.right, ast.Constant)
        ):
            try:
                folded = fn(node.left.value, node.right.value)
            except Exception:
                return node
            if type(folded) is float:
                return node
            return ast.copy_location(ast.Constant(value=folded), node)
        return node

    def visit_UnaryOp(self, node: ast.UnaryOp) -> ast.AST:
        node = self.generic_visit(node)
        fn = _UNARYOPS.get(type(node.op))
        if fn is not None and isinstance(node.operand, ast.Constant):
            try:
                folded = fn(node.operand.value)
            except Exception:
                return node
            if type(folded) is float:
                return node
            return ast.copy_location(ast.Constant(value=folded), node)
        return node

    def visit_Expr(self, node: ast.Expr) -> ast.AST:
        node = self.generic_visit(node)
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return ast.Pass()
        return node


def _parse(source: str) -> ast.AST | None:
    try:
        return ast.parse(source)
    except SyntaxError:
        return None


def _dump(tree: ast.AST) -> str:
    return ast.dump(tree, annotate_fields=True, include_attributes=False)


def _normalized_ir(source: str) -> str | None:
    tree = _parse(source)
    if tree is None:
        return None
    return _dump(_ConstantFolder().visit(tree))


def _const_folded(source: str) -> str | None:
    return _normalized_ir(source)


# ---------------------------------------------------------------------------
# Method evaluation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _MethodEvidence:
    method: str
    verdict: str
    note: str

    def payload(self) -> dict[str, str]:
        return {
            "schema": METHOD_EVIDENCE_SCHEMA,
            "method": self.method,
            "verdict": self.verdict,
            "note": self.note,
        }

    def cid(self) -> str:
        return cid_for_structured(self.payload())


def _compare_texts(left: str | None, right: str | None) -> MethodVerdict:
    if left is None or right is None:
        return MethodVerdict.UNKNOWN
    if left == right:
        return MethodVerdict.EQUIVALENT
    return MethodVerdict.NOT_EQUIVALENT


def _evaluate_methods(subject: EquivalenceSubject) -> tuple[_MethodEvidence, ...]:
    evidence: list[_MethodEvidence] = []

    original_tree = _parse(subject.original_source)
    mutant_tree = _parse(subject.mutant_source)
    if original_tree is None or mutant_tree is None:
        ast_verdict = MethodVerdict.UNKNOWN
        ast_note = "one or both sources failed to parse; AST comparison is unknown"
    else:
        ast_verdict = _compare_texts(_dump(original_tree), _dump(mutant_tree))
        ast_note = (
            "parsed AST dumps are identical"
            if ast_verdict is MethodVerdict.EQUIVALENT
            else "parsed AST dumps differ"
        )
    evidence.append(
        _MethodEvidence(EquivalenceMethod.AST_COMPARISON.value, ast_verdict.value, ast_note)
    )

    supplied_ir = (
        subject.original_normalized_ir is not None
        and subject.mutant_normalized_ir is not None
    )
    if supplied_ir:
        ir_verdict = _compare_texts(
            subject.original_normalized_ir, subject.mutant_normalized_ir
        )
        ir_note = "caller-supplied normalized IR compared"
    else:
        ir_verdict = _compare_texts(
            _normalized_ir(subject.original_source),
            _normalized_ir(subject.mutant_source),
        )
        ir_note = "derived normalized IR (docstring-stripped constant-folded dump)"
        if ir_verdict is MethodVerdict.UNKNOWN:
            ir_note = "normalized IR unavailable because a source did not parse"
    evidence.append(
        _MethodEvidence(EquivalenceMethod.NORMALIZED_IR.value, ir_verdict.value, ir_note)
    )

    const_verdict = _compare_texts(
        _const_folded(subject.original_source), _const_folded(subject.mutant_source)
    )
    const_note = (
        "constant-folded forms compared"
        if const_verdict is not MethodVerdict.UNKNOWN
        else "constant folding unavailable because a source did not parse"
    )
    evidence.append(
        _MethodEvidence(
            EquivalenceMethod.CONSTANT_PROPAGATION.value, const_verdict.value, const_note
        )
    )

    if subject.reachability_observed:
        reach_verdict = _compare_texts(
            subject.original_reachable_fragment, subject.mutant_reachable_fragment
        )
        reach_note = "observed reachable fragments compared"
    else:
        reach_verdict = MethodVerdict.UNAVAILABLE
        reach_note = "reachability not observed; method unavailable"
    evidence.append(
        _MethodEvidence(EquivalenceMethod.REACHABILITY.value, reach_verdict.value, reach_note)
    )

    if subject.symbolic_capability:
        symbolic_verdict = MethodVerdict(subject.symbolic_verdict)
        symbolic_note = "caller-supplied symbolic execution verdict"
    else:
        symbolic_verdict = MethodVerdict.UNAVAILABLE
        symbolic_note = "symbolic execution capability absent; typed unavailable"
    evidence.append(
        _MethodEvidence(
            EquivalenceMethod.SYMBOLIC_EXECUTION.value,
            symbolic_verdict.value,
            symbolic_note,
        )
    )

    if subject.smt_capability:
        smt_verdict = MethodVerdict(subject.smt_verdict)
        smt_note = "caller-supplied restricted SMT verdict"
    else:
        smt_verdict = MethodVerdict.UNAVAILABLE
        smt_note = "restricted SMT capability absent; typed unavailable"
    evidence.append(
        _MethodEvidence(EquivalenceMethod.RESTRICTED_SMT.value, smt_verdict.value, smt_note)
    )

    if subject.bounded_behavior_observed:
        mismatched = [
            pair.input_cid
            for pair in subject.bounded_behavior
            if pair.original_output_cid != pair.mutant_output_cid
        ]
        if mismatched:
            behavior_verdict = MethodVerdict.NOT_EQUIVALENT
            behavior_note = (
                "bounded public outputs differ on inputs: " + ",".join(mismatched)
            )
        else:
            behavior_verdict = MethodVerdict.EQUIVALENT
            behavior_note = "bounded public outputs match on the observed domain"
    else:
        behavior_verdict = MethodVerdict.UNAVAILABLE
        behavior_note = "bounded public behavior not observed; method unavailable"
    evidence.append(
        _MethodEvidence(
            EquivalenceMethod.BOUNDED_PUBLIC_BEHAVIOR.value,
            behavior_verdict.value,
            behavior_note,
        )
    )

    return tuple(evidence)


_SEMANTIC_METHODS: Final[frozenset[str]] = frozenset(
    {
        EquivalenceMethod.SYMBOLIC_EXECUTION.value,
        EquivalenceMethod.RESTRICTED_SMT.value,
        EquivalenceMethod.BOUNDED_PUBLIC_BEHAVIOR.value,
        EquivalenceMethod.REACHABILITY.value,
    }
)


def _compose(
    subject: EquivalenceSubject, evidence: Sequence[_MethodEvidence]
) -> tuple[str, tuple[str, ...], str]:
    """Return (assessment_status, methods, notes).

    Syntactic mismatch (AST / IR / const-fold) is absence of proof, not a
    semantic disproof. Semantic methods and observed reachability may prove
    ``not_equivalent``. ``unknown`` is never rewritten to ``equivalent``.
    """

    by_method = {item.method: item for item in evidence}
    applied = [
        item
        for item in evidence
        if item.verdict != MethodVerdict.UNAVAILABLE.value
    ]
    semantic_diffs = [
        item.method
        for item in applied
        if item.method in _SEMANTIC_METHODS
        and item.verdict == MethodVerdict.NOT_EQUIVALENT.value
    ]
    if semantic_diffs:
        methods = tuple(item.method for item in applied)
        return (
            EquivalenceAssessmentStatus.NOT_EQUIVALENT.value,
            methods,
            "not equivalent: " + ", ".join(semantic_diffs),
        )

    ast_eq = by_method[EquivalenceMethod.AST_COMPARISON.value].verdict == (
        MethodVerdict.EQUIVALENT.value
    )
    ir_eq = by_method[EquivalenceMethod.NORMALIZED_IR.value].verdict == (
        MethodVerdict.EQUIVALENT.value
    )
    const_eq = by_method[EquivalenceMethod.CONSTANT_PROPAGATION.value].verdict == (
        MethodVerdict.EQUIVALENT.value
    )
    reach_eq = by_method[EquivalenceMethod.REACHABILITY.value].verdict == (
        MethodVerdict.EQUIVALENT.value
    )
    symbolic_eq = by_method[EquivalenceMethod.SYMBOLIC_EXECUTION.value].verdict == (
        MethodVerdict.EQUIVALENT.value
    )
    smt_eq = by_method[EquivalenceMethod.RESTRICTED_SMT.value].verdict == (
        MethodVerdict.EQUIVALENT.value
    )
    behavior_eq = by_method[EquivalenceMethod.BOUNDED_PUBLIC_BEHAVIOR.value].verdict == (
        MethodVerdict.EQUIVALENT.value
    )

    proving = ast_eq or ir_eq or const_eq or reach_eq
    stronger_ok = True
    if subject.symbolic_capability and not symbolic_eq:
        stronger_ok = False
    if subject.smt_capability and not smt_eq:
        stronger_ok = False
    if subject.bounded_behavior_observed and not behavior_eq:
        stronger_ok = False

    methods = tuple(item.method for item in applied)
    if proving and stronger_ok and ast_eq:
        return (
            EquivalenceAssessmentStatus.EQUIVALENT.value,
            methods,
            "equivalent by identical parsed AST; stronger methods do not contradict",
        )
    if proving and stronger_ok and (ir_eq or const_eq or reach_eq) and not subject.high_value:
        if subject.symbolic_capability or subject.smt_capability or subject.bounded_behavior_observed:
            if (not subject.symbolic_capability or symbolic_eq) and (
                not subject.smt_capability or smt_eq
            ) and (not subject.bounded_behavior_observed or behavior_eq):
                return (
                    EquivalenceAssessmentStatus.EQUIVALENT.value,
                    methods,
                    "equivalent by normalized IR / constant folding / reachability "
                    "with agreeing observed stronger methods",
                )
        return (
            EquivalenceAssessmentStatus.PROBABLY_EQUIVALENT.value,
            methods,
            "probably equivalent by bounded syntactic methods; symbolic/SMT/"
            "behavior were not all available so equivalent is not automatic",
        )

    if subject.high_value and not ast_eq:
        methods = methods + (EquivalenceMethod.HUMAN_REVIEW.value,)
        return (
            EquivalenceAssessmentStatus.UNKNOWN.value,
            methods,
            "high-value unresolved case escalated to human review; unknown "
            "never becomes equivalent automatically",
        )

    return (
        EquivalenceAssessmentStatus.UNKNOWN.value,
        methods if methods else (EquivalenceMethod.AST_COMPARISON.value,),
        "insufficient bounded evidence; unknown never becomes equivalent automatically",
    )


def _assessment_header(
    base: AssuranceArtifactHeader, *, interface_id: str
) -> AssuranceArtifactHeader:
    generator = GeneratorIdentity(
        generator_id=GENERATOR_ID,
        generator_version=GENERATOR_VERSION,
        interface_id=interface_id,
    )
    versions = VersionBinding(
        operator_id=base.versions.operator_id,
        operator_version=base.versions.operator_version,
        campaign_policy_id=base.versions.campaign_policy_id,
        campaign_policy_version=base.versions.campaign_policy_version,
        generator=generator,
    )
    return AssuranceArtifactHeader(
        artifact_kind="mutation_equivalence_assessment",
        repository_id=base.repository_id,
        repository_state_cid=base.repository_state_cid,
        target_symbol_ids=tuple(base.target_symbol_ids),
        target_artifact_cids=tuple(base.target_artifact_cids),
        capsule_cids=tuple(base.capsule_cids),
        proof_unit_cids=tuple(base.proof_unit_cids),
        environment_cid=base.environment_cid,
        dependency_lock_cid=base.dependency_lock_cid,
        versions=versions,
        provenance=base.provenance,
        terminal_status=base.terminal_status,
        receipt_cids=tuple(base.receipt_cids),
        proof_cids=tuple(base.proof_cids),
        metadata=dict(base.metadata),
    )


def assess_mutation_equivalence(
    subject: EquivalenceSubject | Mapping[str, Any],
    header: AssuranceArtifactHeader | Mapping[str, Any],
    *,
    notes: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> MutationEquivalenceAssessment:
    """Assess whether a mutant is equivalent under bounded current-tree evidence.

    Interface: ``assess_mutation_equivalence@1``

    Fail-closed when observation is incomplete. Difficulty to kill and
    ``likely_equivalent`` never contribute to the status. ``unknown`` is never
    rewritten to ``equivalent``.
    """

    sealed = _normalize_subject(subject)
    if not sealed.observation_complete:
        raise EquivalenceAnalysisError(
            "assess_mutation_equivalence fails closed when observation_complete is false"
        )
    # Explicitly discard non-evidence flags so they cannot leak into status.
    _ = sealed.likely_equivalent
    _ = sealed.difficulty_to_kill

    method_evidence = _evaluate_methods(sealed)
    status, methods, composed_note = _compose(sealed, method_evidence)
    assessment_header = _assessment_header(
        _header(header), interface_id=ASSESS_MUTATION_EQUIVALENCE_INTERFACE
    )
    evidence_cids = [sealed.subject_cid]
    evidence_cids.extend(item.cid() for item in method_evidence)
    result_metadata = dict(metadata or {})
    result_metadata["subject_observation_cid"] = sealed.observation_cid
    result_metadata["method_verdicts"] = {
        item.method: item.verdict for item in method_evidence
    }
    result_metadata["likely_equivalent_ignored"] = True
    result_metadata["difficulty_to_kill_ignored"] = True
    if notes:
        composed_note = f"{composed_note}; {notes}"
    if sealed.notes:
        composed_note = f"{composed_note}; subject: {sealed.notes}"
    try:
        return MutationEquivalenceAssessment(
            header=assessment_header,
            assessment_id=f"{sealed.candidate_id}.equivalence",
            candidate_id=sealed.candidate_id,
            candidate_cid=sealed.candidate_cid,
            assessment_status=status,
            methods=methods,
            evidence_cids=evidence_cids,
            difficulty_to_kill_not_evidence=True,
            notes=composed_note,
            metadata=result_metadata,
        )
    except ExecutionContractError as exc:
        raise EquivalenceAnalysisError(str(exc)) from exc


def verify_equivalence_assessment_identity(
    assessment: MutationEquivalenceAssessment | Mapping[str, Any],
) -> str:
    """Recompute and return the assessment CID; raise on forged input."""

    if isinstance(assessment, MutationEquivalenceAssessment):
        sealed = assessment
    elif isinstance(assessment, Mapping):
        sealed = MutationEquivalenceAssessment.from_dict(assessment)
    else:
        raise EquivalenceAnalysisError(
            "assessment must be MutationEquivalenceAssessment or mapping"
        )
    recomputed = cid_for_structured(sealed.identity_payload())
    if recomputed != sealed.assessment_cid:
        raise EquivalenceAnalysisError(
            "assessment_cid identity mismatch with recomputed identity"
        )
    return recomputed


__all__ = [
    "ASSESS_MUTATION_EQUIVALENCE_INTERFACE",
    "EQUIVALENCE_SUBJECT_INTERFACE",
    "EQUIVALENCE_SUBJECT_SCHEMA",
    "GENERATOR_ID",
    "BoundedBehaviorPair",
    "EquivalenceAnalysisError",
    "EquivalenceSubject",
    "MethodVerdict",
    "assess_mutation_equivalence",
    "equivalence_assessment_statuses",
    "equivalence_methods",
    "verify_equivalence_assessment_identity",
]
