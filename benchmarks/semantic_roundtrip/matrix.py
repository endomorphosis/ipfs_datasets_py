"""Eight-cell constructor-by-realizer semantic round-trip runner.

The runner composes the four preregistered constructors with the two common
realizers.  For each case, a constructor is invoked once on T0 and that exact
canonical L1 payload is fanned out to both realizers.  Each resulting T1 is
then passed to the same constructor object with the same frozen request
configuration.  Semantic artifacts are content-addressed before optional
Hammer/cvc5 and Lean validators are invoked.
"""

from __future__ import annotations

import re
import shutil
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final, Protocol

from benchmarks.logic_pipeline.content_addressing import (
    cid_for_bytes,
    cid_for_dag_json,
)
from benchmarks.semantic_roundtrip.contracts import (
    AllowedAtomVocabulary,
    CanonicalRuleIR,
    ComponentStatus,
    ConstructorRequest,
    ConstructorResult,
    ContractError,
    FailureReason,
    RealizerRequest,
    RealizerResult,
    RoundTripConstructor,
    RoundTripRealizer,
    RoundTripResult,
)
from benchmarks.semantic_roundtrip.metrics import (
    compare_semantic_ir,
    make_round_trip_result,
)


SEMANTIC_ROUND_TRIP_MATRIX_INTERFACE: Final = "SemanticRoundTripMatrix@1"
MATRIX_CONSTRUCTOR_IDS: Final = (
    "typed_deontic",
    "modal_spacy",
    "leanstral_direct",
    "leanstral_spacy_evidence",
)
MATRIX_REALIZER_IDS: Final = ("deterministic", "leanstral")
EXPECTED_CELL_IDS: Final = tuple(
    f"{constructor_id}__{realizer_id}"
    for constructor_id in MATRIX_CONSTRUCTOR_IDS
    for realizer_id in MATRIX_REALIZER_IDS
)
MATRIX_CONSTRUCTORS: Final = MATRIX_CONSTRUCTOR_IDS
MATRIX_REALIZERS: Final = MATRIX_REALIZER_IDS
COPY_NGRAM_WIDTH: Final = 8
COPY_PRECISION_LIMIT: Final = 0.80
_TOKEN_RE: Final = re.compile(r"[a-z0-9]+")


def _plain_json(value: object) -> object:
    """Return a detached, JSON-compatible representation."""

    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain_json(item) for item in value]
    if isinstance(value, list):
        return [_plain_json(item) for item in value]
    return value


def _freeze_json(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_json(item) for item in value)
    return value


def _identity(component: object, *, role: str) -> str:
    identity = getattr(component, "identity", None)
    if not isinstance(identity, str) or not identity.strip():
        raise ContractError(f"{role} identity must be a nonblank string")
    return identity


def _tokens(value: str) -> tuple[str, ...]:
    words = _TOKEN_RE.findall(" ".join(value.strip().split()).lower())
    normalized: list[str] = []
    for word in words:
        if len(word) > 4 and word.endswith("ies"):
            word = word[:-3] + "y"
        elif len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        normalized.append(word)
    return tuple(normalized)


def source_copy_diagnostics(
    source_text: str,
    reconstruction: str | None,
) -> dict[str, object]:
    """Measure the frozen normalized-copy and eight-token overlap gates."""

    if not isinstance(source_text, str):
        raise ContractError("source_text must be a string")
    source_tokens = _tokens(source_text)
    output_tokens = (
        _tokens(reconstruction) if isinstance(reconstruction, str) else ()
    )

    def ngrams(tokens: tuple[str, ...]) -> Counter[tuple[str, ...]]:
        return Counter(
            tuple(tokens[index : index + COPY_NGRAM_WIDTH])
            for index in range(
                max(0, len(tokens) - COPY_NGRAM_WIDTH + 1)
            )
        )

    source_ngrams = ngrams(source_tokens)
    output_ngrams = ngrams(output_tokens)
    copied = sum((source_ngrams & output_ngrams).values())
    output_total = sum(output_ngrams.values())
    source_total = sum(source_ngrams.values())
    exact = bool(
        source_tokens and output_tokens and source_tokens == output_tokens
    )
    precision = copied / output_total if output_total else 0.0
    recall = copied / source_total if source_total else 0.0
    copy_risk = exact or precision >= COPY_PRECISION_LIMIT
    evaluated = isinstance(reconstruction, str) and bool(
        reconstruction.strip()
    )
    return {
        "evaluated": evaluated,
        "normalization": "lowercase_token_plural_normalization_v1",
        "ngram_width": COPY_NGRAM_WIDTH,
        "precision_limit_exclusive": COPY_PRECISION_LIMIT,
        "exact_normalized_copy": exact,
        "source_token_count": len(source_tokens),
        "reconstruction_token_count": len(output_tokens),
        "shared_8gram_count": copied,
        "shared_8gram_precision": round(precision, 9),
        "shared_8gram_recall": round(recall, 9),
        "copy_risk": copy_risk,
        "gate_passed": bool(evaluated and not copy_risk),
    }


# Compatibility with the historical pilot's public diagnostic name.
source_copy_metrics = source_copy_diagnostics


def polarity_diagnostics(
    gold_ir: CanonicalRuleIR,
    l2: CanonicalRuleIR | None,
) -> dict[str, object]:
    """Report polarity preservation in the gold-to-L2 optimal assignment."""

    if not isinstance(gold_ir, CanonicalRuleIR):
        raise ContractError("gold_ir must be CanonicalRuleIR")
    if l2 is None:
        return {
            "evaluated": False,
            "assigned_rule_count": 0,
            "preserved_rule_count": 0,
            "inversion_count": 0,
            "inversions": [],
            "all_assigned_preserved": False,
            "gate_passed": False,
        }
    comparison = compare_semantic_ir(gold_ir, l2)
    matches = comparison["matches"]
    assert isinstance(matches, list)
    inversions = [
        {
            "reference_index": match["reference_index"],
            "candidate_index": match["candidate_index"],
        }
        for match in matches
        if not bool(match["modality_preserved"])
    ]
    preserved = len(matches) - len(inversions)
    all_preserved = not inversions
    return {
        "evaluated": True,
        "assigned_rule_count": len(matches),
        "preserved_rule_count": preserved,
        "inversion_count": len(inversions),
        "inversions": inversions,
        "all_assigned_preserved": all_preserved,
        "gate_passed": all_preserved,
    }


@dataclass(frozen=True, slots=True)
class MatrixCase:
    """One frozen source, vocabulary, and adjudicated scoring target."""

    case_id: str
    source_text: str
    allowed_atom_vocabulary: AllowedAtomVocabulary
    gold_ir: CanonicalRuleIR

    def __post_init__(self) -> None:
        if not isinstance(self.case_id, str) or not self.case_id.strip():
            raise ContractError("case_id must be a nonblank string")
        if not isinstance(self.source_text, str) or not self.source_text.strip():
            raise ContractError("source_text must be a nonblank string")
        if not isinstance(
            self.allowed_atom_vocabulary, AllowedAtomVocabulary
        ):
            raise ContractError(
                "allowed_atom_vocabulary must be AllowedAtomVocabulary"
            )
        if not isinstance(self.gold_ir, CanonicalRuleIR):
            raise ContractError("gold_ir must be CanonicalRuleIR")
        if self.gold_ir.is_empty:
            raise ContractError("gold_ir must be nonempty")
        self.gold_ir.validate_vocabulary(self.allowed_atom_vocabulary)

    @classmethod
    def from_dict(cls, value: object) -> "MatrixCase":
        if not isinstance(value, Mapping):
            raise ContractError("matrix case must be an object")
        case_id = value.get("case_id", value.get("id"))
        vocabulary_value = value.get(
            "allowed_atom_vocabulary", value.get("allowed_atoms")
        )
        vocabulary = AllowedAtomVocabulary.from_dict(vocabulary_value)
        gold = CanonicalRuleIR.from_dict(value.get("gold_ir"), vocabulary)
        return cls(
            case_id=case_id,  # type: ignore[arg-type]
            source_text=value.get("source_text"),  # type: ignore[arg-type]
            allowed_atom_vocabulary=vocabulary,
            gold_ir=gold,
        )

    @property
    def source_text_cid(self) -> str:
        return cid_for_bytes(self.source_text.encode("utf-8"))

    @property
    def gold_ir_cid(self) -> str:
        return cid_for_dag_json(self.gold_ir.to_dict())

    @property
    def case_cid(self) -> str:
        return cid_for_dag_json(
            {
                "case_id": self.case_id,
                "source_text_cid": self.source_text_cid,
                "allowed_atom_vocabulary": (
                    self.allowed_atom_vocabulary.to_dict()
                ),
                "gold_ir_cid": self.gold_ir_cid,
            }
        )


class PostHocValidator(Protocol):
    """A validator that annotates already-bound L1/L2 artifacts."""

    def __call__(
        self,
        left: CanonicalRuleIR,
        right: CanonicalRuleIR,
        request_id: str,
    ) -> Mapping[str, object]:
        """Return a JSON-compatible proof-validation receipt."""


@dataclass(frozen=True, slots=True)
class MatrixCoordinateRecord:
    """CID-addressed terminal result for one matrix cell and one case."""

    case_id: str
    case_cid: str
    cell_id: str
    constructor_id: str
    constructor_identity: str
    realizer_id: str
    realizer_identity: str
    result: RoundTripResult
    l1_cid: str | None
    reconstruction_cid: str | None
    l2_cid: str | None
    diagnostics: Mapping[str, object]
    candidate_cid: str
    validation: Mapping[str, object]
    record_cid: str

    @property
    def status(self) -> ComponentStatus:
        return self.result.status

    @property
    def primary_loss(self) -> float:
        return self.result.primary_loss

    @property
    def coordinate_cid(self) -> str:
        return self.record_cid

    @property
    def cid(self) -> str:
        return self.record_cid

    def _payload(self) -> dict[str, object]:
        return {
            "interface": SEMANTIC_ROUND_TRIP_MATRIX_INTERFACE,
            "case_id": self.case_id,
            "case_cid": self.case_cid,
            "cell_id": self.cell_id,
            "constructor": {
                "id": self.constructor_id,
                "identity": self.constructor_identity,
            },
            "realizer": {
                "id": self.realizer_id,
                "identity": self.realizer_identity,
            },
            "status": self.result.status.value,
            "failure": (
                None
                if self.result.failure_reason is None
                else {
                    "reason": self.result.failure_reason.value,
                    "detail": self.result.failure_detail,
                }
            ),
            "artifacts": {
                "l1": (
                    self.result.l1.to_dict()
                    if self.result.l1 is not None
                    else None
                ),
                "l1_cid": self.l1_cid,
                "t1": self.result.reconstruction,
                "t1_cid": self.reconstruction_cid,
                "l2": (
                    self.result.l2.to_dict()
                    if self.result.l2 is not None
                    else None
                ),
                "l2_cid": self.l2_cid,
            },
            "losses": {
                "forward": self.result.forward_loss,
                "cycle": self.result.cycle_loss,
                "end_to_end": self.result.end_to_end_loss,
                "primary": self.result.primary_loss,
            },
            "diagnostics": _plain_json(self.diagnostics),
            "candidate_cid": self.candidate_cid,
            "validation": _plain_json(self.validation),
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "record_cid": self.record_cid}


@dataclass(frozen=True, slots=True)
class MatrixCaseRecord:
    """The eight terminal coordinate records for one case."""

    case_id: str
    case_cid: str
    source_text_cid: str
    gold_ir_cid: str
    coordinates: tuple[MatrixCoordinateRecord, ...]
    record_cid: str

    @property
    def case_record_cid(self) -> str:
        return self.record_cid

    @property
    def case_result_cid(self) -> str:
        return self.record_cid

    @property
    def cid(self) -> str:
        return self.record_cid

    def _payload(self) -> dict[str, object]:
        return {
            "interface": SEMANTIC_ROUND_TRIP_MATRIX_INTERFACE,
            "case_id": self.case_id,
            "case_cid": self.case_cid,
            "source_text_cid": self.source_text_cid,
            "gold_ir_cid": self.gold_ir_cid,
            "coordinate_count": len(self.coordinates),
            "coordinate_record_cids": [
                coordinate.record_cid for coordinate in self.coordinates
            ],
            "coordinates": [
                coordinate.to_dict() for coordinate in self.coordinates
            ],
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "record_cid": self.record_cid}


@dataclass(frozen=True, slots=True)
class MatrixRunResult:
    """Complete matrix output with failure-preserving cell denominators."""

    cases: tuple[MatrixCaseRecord, ...]
    summaries: Mapping[str, object]
    run_cid: str

    @property
    def cid(self) -> str:
        return self.run_cid

    @property
    def coordinates(self) -> tuple[MatrixCoordinateRecord, ...]:
        return tuple(
            coordinate
            for case in self.cases
            for coordinate in case.coordinates
        )

    def _payload(self) -> dict[str, object]:
        return {
            "interface": SEMANTIC_ROUND_TRIP_MATRIX_INTERFACE,
            "matrix_shape": {
                "constructor_count": len(MATRIX_CONSTRUCTOR_IDS),
                "realizer_count": len(MATRIX_REALIZER_IDS),
                "cell_count": len(EXPECTED_CELL_IDS),
            },
            "case_count": len(self.cases),
            "case_record_cids": [case.record_cid for case in self.cases],
            "cases": [case.to_dict() for case in self.cases],
            "summaries": _plain_json(self.summaries),
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "run_cid": self.run_cid}


def _safe_construct(
    constructor: RoundTripConstructor,
    request: ConstructorRequest,
) -> ConstructorResult:
    try:
        result = constructor.construct(request)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:
        return ConstructorResult(
            status=ComponentStatus.FAILED,
            failure_reason=FailureReason.EXCEPTION,
            failure_detail=(
                f"constructor raised {type(exc).__name__}"
            )[:1000],
        )
    if not isinstance(result, ConstructorResult):
        return ConstructorResult(
            status=ComponentStatus.FAILED,
            failure_reason=FailureReason.INVALID_OUTPUT,
            failure_detail="constructor returned a non-ConstructorResult",
        )
    return result


def _safe_realize(
    realizer: RoundTripRealizer,
    request: RealizerRequest,
) -> RealizerResult:
    try:
        result = realizer.realize(request)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:
        return RealizerResult(
            status=ComponentStatus.FAILED,
            failure_reason=FailureReason.EXCEPTION,
            failure_detail=f"realizer raised {type(exc).__name__}"[:1000],
        )
    if not isinstance(result, RealizerResult):
        return RealizerResult(
            status=ComponentStatus.FAILED,
            failure_reason=FailureReason.INVALID_OUTPUT,
            failure_detail="realizer returned a non-RealizerResult",
        )
    return result


def _semantic_payload(
    *,
    case: MatrixCase,
    cell_id: str,
    constructor_id: str,
    constructor_identity: str,
    realizer_id: str,
    realizer_identity: str,
    result: RoundTripResult,
    l1_cid: str | None,
    reconstruction_cid: str | None,
    l2_cid: str | None,
    diagnostics: Mapping[str, object],
) -> dict[str, object]:
    """Payload bound before proof validators can observe the artifacts."""

    return {
        "interface": SEMANTIC_ROUND_TRIP_MATRIX_INTERFACE,
        "case_id": case.case_id,
        "case_cid": case.case_cid,
        "cell_id": cell_id,
        "constructor": {
            "id": constructor_id,
            "identity": constructor_identity,
        },
        "realizer": {
            "id": realizer_id,
            "identity": realizer_identity,
        },
        "status": result.status.value,
        "failure": (
            None
            if result.failure_reason is None
            else {
                "reason": result.failure_reason.value,
                "detail": result.failure_detail,
            }
        ),
        "artifacts": {
            "l1": result.l1.to_dict() if result.l1 is not None else None,
            "l1_cid": l1_cid,
            "t1": result.reconstruction,
            "t1_cid": reconstruction_cid,
            "l2": result.l2.to_dict() if result.l2 is not None else None,
            "l2_cid": l2_cid,
        },
        "losses": {
            "forward": result.forward_loss,
            "cycle": result.cycle_loss,
            "end_to_end": result.end_to_end_loss,
            "primary": result.primary_loss,
        },
        "diagnostics": _plain_json(diagnostics),
    }


def _default_hammer_validator(
    left: CanonicalRuleIR,
    right: CanonicalRuleIR,
    request_id: str,
) -> Mapping[str, object]:
    from benchmarks.bench_semantic_logic_roundtrip import (
        hammer_cvc5_equivalence,
    )

    return hammer_cvc5_equivalence(
        left.to_dict(),
        right.to_dict(),
        request_id=request_id,
    )


def _lean_validator(lean_path: str | None) -> PostHocValidator:
    def validate(
        left: CanonicalRuleIR,
        right: CanonicalRuleIR,
        request_id: str,
    ) -> Mapping[str, object]:
        del request_id
        if lean_path is None:
            return {
                "status": "unavailable",
                "validator": "lean_native_kernel",
                "benchmark_accepted": False,
                "reason": "Lean executable is unavailable",
            }
        from benchmarks.bench_semantic_logic_roundtrip import (
            lean_exact_identity,
        )

        return lean_exact_identity(
            left.to_dict(), right.to_dict(), lean_path=lean_path
        )

    return validate


def default_post_hoc_validators(
    *,
    lean_path: str | None = None,
) -> dict[str, PostHocValidator]:
    """Return the preregistered validators without executing either one."""

    resolved_lean = lean_path if lean_path is not None else shutil.which("lean")
    return {
        "hammer_cvc5": _default_hammer_validator,
        "lean": _lean_validator(resolved_lean),
    }


class SemanticRoundTripMatrix:
    """Run every registered constructor against every registered realizer."""

    interface: Final = SEMANTIC_ROUND_TRIP_MATRIX_INTERFACE

    def __init__(
        self,
        constructors: Mapping[str, RoundTripConstructor],
        realizers: Mapping[str, RoundTripRealizer],
        *,
        constructor_configs: Mapping[str, Mapping[str, object]] | None = None,
        realizer_configs: Mapping[str, Mapping[str, object]] | None = None,
        validators: Mapping[str, PostHocValidator] | None = None,
        require_eight_cells: bool = True,
    ) -> None:
        supplied_constructors = dict(constructors)
        supplied_realizers = dict(realizers)
        if not supplied_constructors or not supplied_realizers:
            raise ContractError(
                "matrix requires nonempty constructor and realizer registries"
            )
        if require_eight_cells:
            if set(supplied_constructors) != set(MATRIX_CONSTRUCTOR_IDS):
                raise ContractError(
                    "constructor registry must contain the four frozen arms "
                )
            if set(supplied_realizers) != set(MATRIX_REALIZER_IDS):
                raise ContractError(
                    "realizer registry must contain the two frozen arms "
                )
            self._constructors = {
                component_id: supplied_constructors[component_id]
                for component_id in MATRIX_CONSTRUCTOR_IDS
            }
            self._realizers = {
                component_id: supplied_realizers[component_id]
                for component_id in MATRIX_REALIZER_IDS
            }
        else:
            self._constructors = supplied_constructors
            self._realizers = supplied_realizers
        for component in self._constructors.values():
            _identity(component, role="constructor")
        for component in self._realizers.values():
            _identity(component, role="realizer")

        self._constructor_configs = self._validate_configs(
            constructor_configs or {}, self._constructors, "constructor"
        )
        self._realizer_configs = self._validate_configs(
            realizer_configs or {}, self._realizers, "realizer"
        )
        selected_validators = (
            default_post_hoc_validators()
            if validators is None
            else dict(validators)
        )
        if any(
            not isinstance(name, str)
            or not name
            or not callable(validator)
            for name, validator in selected_validators.items()
        ):
            raise ContractError(
                "validator registry must map nonblank ids to callables"
            )
        self._validators = selected_validators

    @property
    def identity(self) -> str:
        return self.interface

    @staticmethod
    def _validate_configs(
        configs: Mapping[str, Mapping[str, object]],
        components: Mapping[str, object],
        role: str,
    ) -> dict[str, dict[str, object]]:
        extra = set(configs) - set(components)
        if extra:
            raise ContractError(
                f"{role} configs contain unknown ids: {sorted(extra)!r}"
            )
        result: dict[str, dict[str, object]] = {}
        for component_id in components:
            value = configs.get(component_id, {})
            if not isinstance(value, Mapping):
                raise ContractError(
                    f"{role} config {component_id!r} must be an object"
                )
            # ConstructorRequest/RealizerRequest perform bounded deep freezing.
            detached = _plain_json(value)
            assert isinstance(detached, dict)
            result[component_id] = detached
        return result

    @property
    def cell_ids(self) -> tuple[str, ...]:
        return tuple(
            f"{constructor_id}__{realizer_id}"
            for constructor_id in self._constructors
            for realizer_id in self._realizers
        )

    @property
    def constructor_ids(self) -> tuple[str, ...]:
        return tuple(self._constructors)

    @property
    def realizer_ids(self) -> tuple[str, ...]:
        return tuple(self._realizers)

    def _failed_record(
        self,
        *,
        case: MatrixCase,
        constructor_id: str,
        constructor_identity: str,
        realizer_id: str,
        realizer_identity: str,
        l1: CanonicalRuleIR | None,
        reconstruction: str | None,
        reason: FailureReason,
        detail: str | None,
    ) -> MatrixCoordinateRecord:
        result = make_round_trip_result(
            case.gold_ir,
            l1,
            reconstruction,
            None,
            failure_reason=reason,
            failure_detail=detail,
        )
        return self._seal_coordinate(
            case=case,
            constructor_id=constructor_id,
            constructor_identity=constructor_identity,
            realizer_id=realizer_id,
            realizer_identity=realizer_identity,
            result=result,
        )

    def _seal_coordinate(
        self,
        *,
        case: MatrixCase,
        constructor_id: str,
        constructor_identity: str,
        realizer_id: str,
        realizer_identity: str,
        result: RoundTripResult,
    ) -> MatrixCoordinateRecord:
        cell_id = f"{constructor_id}__{realizer_id}"
        l1_cid = (
            cid_for_dag_json(result.l1.to_dict())
            if result.l1 is not None
            else None
        )
        reconstruction_cid = (
            cid_for_bytes(result.reconstruction.encode("utf-8"))
            if result.reconstruction is not None
            else None
        )
        l2_cid = (
            cid_for_dag_json(result.l2.to_dict())
            if result.l2 is not None
            else None
        )
        copy = source_copy_diagnostics(
            case.source_text, result.reconstruction
        )
        polarity = polarity_diagnostics(case.gold_ir, result.l2)
        semantic_comparisons: dict[str, object | None] = {
            "forward_gold_to_l1": (
                compare_semantic_ir(case.gold_ir, result.l1)
                if result.l1 is not None
                else None
            ),
            "cycle_l1_to_l2": (
                compare_semantic_ir(result.l1, result.l2)
                if result.l1 is not None and result.l2 is not None
                else None
            ),
            "end_to_end_gold_to_l2": (
                compare_semantic_ir(case.gold_ir, result.l2)
                if result.l2 is not None
                else None
            ),
        }
        full_coverage = result.is_complete
        gates = {
            "full_coverage": full_coverage,
            "source_copy_exclusion": bool(copy["gate_passed"]),
            "polarity_preservation": bool(polarity["gate_passed"]),
        }
        gates["selection_eligible"] = all(gates.values())
        diagnostics: Mapping[str, object] = {
            "semantic_comparisons": semantic_comparisons,
            "source_copy": copy,
            "polarity": polarity,
            "gates": gates,
            "l1_payload_cid": l1_cid,
            "constructor_config_cid": cid_for_dag_json(
                self._constructor_configs[constructor_id]
            ),
            "realizer_config_cid": cid_for_dag_json(
                self._realizer_configs[realizer_id]
            ),
            "same_constructor_reapplied": bool(
                result.reconstruction is not None
            ),
        }
        semantic_payload = _semantic_payload(
            case=case,
            cell_id=cell_id,
            constructor_id=constructor_id,
            constructor_identity=constructor_identity,
            realizer_id=realizer_id,
            realizer_identity=realizer_identity,
            result=result,
            l1_cid=l1_cid,
            reconstruction_cid=reconstruction_cid,
            l2_cid=l2_cid,
            diagnostics=diagnostics,
        )
        candidate_cid = cid_for_dag_json(semantic_payload)

        validation_results: dict[str, object] = {}
        validation_status = "not_applicable"
        if result.is_complete:
            validation_status = "success"
            assert result.l1 is not None
            assert result.l2 is not None
            request_id = re.sub(
                r"[^A-Za-z0-9_.:-]",
                "_",
                f"{case.case_id}:{cell_id}:{candidate_cid}",
            )[:120]
            for validator_id, validator in self._validators.items():
                try:
                    receipt = validator(result.l1, result.l2, request_id)
                    if not isinstance(receipt, Mapping):
                        raise TypeError(
                            "validator returned a non-object receipt"
                        )
                    validation_results[validator_id] = _plain_json(receipt)
                except (KeyboardInterrupt, SystemExit):
                    raise
                except BaseException as exc:
                    validation_status = "failed"
                    validation_results[validator_id] = {
                        "status": "failed",
                        "failure_type": type(exc).__name__,
                        "failure_detail": (
                            f"post-hoc validator failed: {type(exc).__name__}"
                        ),
                    }
        else:
            for validator_id in self._validators:
                validation_results[validator_id] = {
                    "status": "not_applicable",
                    "reason": "coordinate did not produce nonempty L1 and L2",
                }

        # Recompute from the immutable semantic objects after all validators.
        candidate_unchanged = (
            cid_for_dag_json(
                _semantic_payload(
                    case=case,
                    cell_id=cell_id,
                    constructor_id=constructor_id,
                    constructor_identity=constructor_identity,
                    realizer_id=realizer_id,
                    realizer_identity=realizer_identity,
                    result=result,
                    l1_cid=l1_cid,
                    reconstruction_cid=reconstruction_cid,
                    l2_cid=l2_cid,
                    diagnostics=diagnostics,
                )
            )
            == candidate_cid
        )
        if not candidate_unchanged:
            raise ContractError(
                "post-hoc validation changed a bound semantic candidate"
            )
        validation: Mapping[str, object] = {
            "phase": "post_hoc_after_candidate_binding",
            "status": validation_status,
            "candidate_cid": candidate_cid,
            "candidate_unchanged": True,
            "scope": (
                "Exact nonvacuous canonical L1/L2 identity only; validation "
                "does not change candidates, losses, gates, or denominators."
            ),
            "results": validation_results,
            **validation_results,
        }

        provisional = MatrixCoordinateRecord(
            case_id=case.case_id,
            case_cid=case.case_cid,
            cell_id=cell_id,
            constructor_id=constructor_id,
            constructor_identity=constructor_identity,
            realizer_id=realizer_id,
            realizer_identity=realizer_identity,
            result=result,
            l1_cid=l1_cid,
            reconstruction_cid=reconstruction_cid,
            l2_cid=l2_cid,
            diagnostics=_freeze_json(diagnostics),  # type: ignore[arg-type]
            candidate_cid=candidate_cid,
            validation=_freeze_json(validation),  # type: ignore[arg-type]
            record_cid="",
        )
        record_cid = cid_for_dag_json(provisional._payload())
        return MatrixCoordinateRecord(
            case_id=provisional.case_id,
            case_cid=provisional.case_cid,
            cell_id=provisional.cell_id,
            constructor_id=provisional.constructor_id,
            constructor_identity=provisional.constructor_identity,
            realizer_id=provisional.realizer_id,
            realizer_identity=provisional.realizer_identity,
            result=provisional.result,
            l1_cid=provisional.l1_cid,
            reconstruction_cid=provisional.reconstruction_cid,
            l2_cid=provisional.l2_cid,
            diagnostics=provisional.diagnostics,
            candidate_cid=provisional.candidate_cid,
            validation=provisional.validation,
            record_cid=record_cid,
        )

    def run_case(self, case: MatrixCase) -> MatrixCaseRecord:
        """Execute all cells for one case and return its CID-addressed record."""

        if not isinstance(case, MatrixCase):
            raise ContractError("case must be MatrixCase")
        coordinates: list[MatrixCoordinateRecord] = []
        for constructor_id, constructor in self._constructors.items():
            constructor_identity = _identity(
                constructor, role="constructor"
            )
            constructor_config = self._constructor_configs[constructor_id]
            initial_request = ConstructorRequest(
                source_text=case.source_text,
                allowed_atom_vocabulary=case.allowed_atom_vocabulary,
                config=constructor_config,
            )
            initial = _safe_construct(constructor, initial_request)
            if initial.status is ComponentStatus.FAILED:
                assert initial.failure_reason is not None
                for realizer_id, realizer in self._realizers.items():
                    coordinates.append(
                        self._failed_record(
                            case=case,
                            constructor_id=constructor_id,
                            constructor_identity=constructor_identity,
                            realizer_id=realizer_id,
                            realizer_identity=_identity(
                                realizer, role="realizer"
                            ),
                            l1=None,
                            reconstruction=None,
                            reason=initial.failure_reason,
                            detail=initial.failure_detail,
                        )
                    )
                continue

            l1 = initial.canonical_ir
            assert l1 is not None
            # Serialize once, then deserialize at each strict realizer boundary.
            # This makes the fan-out payload equality explicit and testable.
            l1_payload = {
                "canonical_ir": l1.to_dict(),
                "allowed_atom_vocabulary": (
                    case.allowed_atom_vocabulary.to_dict()
                ),
                "config": {},
            }
            for realizer_id, realizer in self._realizers.items():
                realizer_identity = _identity(realizer, role="realizer")
                payload = {
                    **l1_payload,
                    "config": self._realizer_configs[realizer_id],
                }
                realizer_request = RealizerRequest.from_payload(payload)
                realized = _safe_realize(realizer, realizer_request)
                if realized.status is ComponentStatus.FAILED:
                    assert realized.failure_reason is not None
                    coordinates.append(
                        self._failed_record(
                            case=case,
                            constructor_id=constructor_id,
                            constructor_identity=constructor_identity,
                            realizer_id=realizer_id,
                            realizer_identity=realizer_identity,
                            l1=l1,
                            reconstruction=None,
                            reason=realized.failure_reason,
                            detail=realized.failure_detail,
                        )
                    )
                    continue

                reconstruction = realized.text
                assert reconstruction is not None
                # ConstructorRequest performs the same deep config freeze as
                # the initial call.  Identity is checked around the second call.
                second_request = ConstructorRequest(
                    source_text=reconstruction,
                    allowed_atom_vocabulary=case.allowed_atom_vocabulary,
                    config=constructor_config,
                )
                second = _safe_construct(constructor, second_request)
                if _identity(constructor, role="constructor") != (
                    constructor_identity
                ):
                    second = ConstructorResult(
                        status=ComponentStatus.FAILED,
                        failure_reason=FailureReason.INVALID_OUTPUT,
                        failure_detail=(
                            "constructor identity changed between L1 and L2"
                        ),
                    )
                if second.status is ComponentStatus.FAILED:
                    reason = second.failure_reason
                    assert reason is not None
                    if reason is FailureReason.EMPTY_L1:
                        reason = FailureReason.EMPTY_L2
                    coordinates.append(
                        self._failed_record(
                            case=case,
                            constructor_id=constructor_id,
                            constructor_identity=constructor_identity,
                            realizer_id=realizer_id,
                            realizer_identity=realizer_identity,
                            l1=l1,
                            reconstruction=reconstruction,
                            reason=reason,
                            detail=second.failure_detail,
                        )
                    )
                    continue

                result = make_round_trip_result(
                    case.gold_ir,
                    l1,
                    reconstruction,
                    second.canonical_ir,
                )
                coordinates.append(
                    self._seal_coordinate(
                        case=case,
                        constructor_id=constructor_id,
                        constructor_identity=constructor_identity,
                        realizer_id=realizer_id,
                        realizer_identity=realizer_identity,
                        result=result,
                    )
                )

        expected_count = len(self._constructors) * len(self._realizers)
        if len(coordinates) != expected_count:
            raise ContractError(
                "matrix did not retain every scheduled coordinate"
            )
        provisional = MatrixCaseRecord(
            case_id=case.case_id,
            case_cid=case.case_cid,
            source_text_cid=case.source_text_cid,
            gold_ir_cid=case.gold_ir_cid,
            coordinates=tuple(coordinates),
            record_cid="",
        )
        record_cid = cid_for_dag_json(provisional._payload())
        return MatrixCaseRecord(
            case_id=provisional.case_id,
            case_cid=provisional.case_cid,
            source_text_cid=provisional.source_text_cid,
            gold_ir_cid=provisional.gold_ir_cid,
            coordinates=provisional.coordinates,
            record_cid=record_cid,
        )

    def run(self, cases: Sequence[MatrixCase]) -> MatrixRunResult:
        """Execute cases in order and retain failures in every cell mean."""

        if (
            not isinstance(cases, Sequence)
            or isinstance(cases, (str, bytes, bytearray))
            or not cases
        ):
            raise ContractError("cases must be a nonempty sequence")
        seen: set[str] = set()
        case_records: list[MatrixCaseRecord] = []
        for case in cases:
            if not isinstance(case, MatrixCase):
                raise ContractError("cases must contain MatrixCase values")
            if case.case_id in seen:
                raise ContractError("case ids must be unique")
            seen.add(case.case_id)
            case_records.append(self.run_case(case))

        summaries: dict[str, object] = {}
        for cell_id in self.cell_ids:
            records = [
                next(
                    coordinate
                    for coordinate in case.coordinates
                    if coordinate.cell_id == cell_id
                )
                for case in case_records
            ]
            denominator = len(records)
            summaries[cell_id] = {
                "scheduled_case_count": denominator,
                "denominator_policy": (
                    "all_scheduled_cases_including_failures"
                ),
                "success_count": sum(
                    record.status is ComponentStatus.SUCCESS
                    for record in records
                ),
                "failure_count": sum(
                    record.status is ComponentStatus.FAILED
                    for record in records
                ),
                "mean_forward_loss": round(
                    sum(record.result.forward_loss for record in records)
                    / denominator,
                    9,
                ),
                "mean_cycle_loss": round(
                    sum(record.result.cycle_loss for record in records)
                    / denominator,
                    9,
                ),
                "mean_end_to_end_loss": round(
                    sum(record.result.end_to_end_loss for record in records)
                    / denominator,
                    9,
                ),
                "selection_eligible": all(
                    bool(
                        record.diagnostics["gates"][  # type: ignore[index]
                            "selection_eligible"
                        ]
                    )
                    for record in records
                ),
                "coordinate_record_cids": [
                    record.record_cid for record in records
                ],
            }
        frozen_summaries = _freeze_json(summaries)
        provisional = MatrixRunResult(
            cases=tuple(case_records),
            summaries=frozen_summaries,  # type: ignore[arg-type]
            run_cid="",
        )
        run_cid = cid_for_dag_json(provisional._payload())
        return MatrixRunResult(
            cases=provisional.cases,
            summaries=provisional.summaries,
            run_cid=run_cid,
        )


# More concise name for callers that already import from this module.
MatrixRunner = SemanticRoundTripMatrix
MatrixCellResult = MatrixCoordinateRecord
MatrixCaseResult = MatrixCaseRecord


def default_component_registries(
    *,
    leanstral_client: object | None = None,
    spacy_pipeline: object | None = None,
) -> tuple[
    dict[str, RoundTripConstructor],
    dict[str, RoundTripRealizer],
]:
    """Instantiate the frozen four-by-two adapter inventory."""

    from benchmarks.semantic_roundtrip.constructors.leanstral import (
        LeanstralCanonicalConstructor,
        LeanstralConstructorArm,
    )
    from benchmarks.semantic_roundtrip.constructors.modal_spacy import (
        ModalSpacyCanonicalConstructor,
    )
    from benchmarks.semantic_roundtrip.constructors.typed_deontic import (
        TypedDeonticCanonicalConstructor,
    )
    from benchmarks.semantic_roundtrip.realizers.deterministic import (
        CanonicalDeterministicRealizer,
    )
    from benchmarks.semantic_roundtrip.realizers.leanstral import (
        LeanstralCanonicalRealizer,
    )

    constructors: dict[str, RoundTripConstructor] = {
        "typed_deontic": TypedDeonticCanonicalConstructor(),
        "modal_spacy": ModalSpacyCanonicalConstructor(),
        "leanstral_direct": LeanstralCanonicalConstructor(
            leanstral_client  # type: ignore[arg-type]
        ),
        "leanstral_spacy_evidence": LeanstralCanonicalConstructor(
            leanstral_client,  # type: ignore[arg-type]
            arm=LeanstralConstructorArm.SPACY_EVIDENCE,
            spacy_pipeline=spacy_pipeline,
        ),
    }
    realizers: dict[str, RoundTripRealizer] = {
        "deterministic": CanonicalDeterministicRealizer(),
        "leanstral": LeanstralCanonicalRealizer(
            leanstral_client  # type: ignore[arg-type]
        ),
    }
    return constructors, realizers


def default_matrix(
    *,
    leanstral_client: object | None = None,
    spacy_pipeline: object | None = None,
    validators: Mapping[str, PostHocValidator] | None = None,
) -> SemanticRoundTripMatrix:
    constructors, realizers = default_component_registries(
        leanstral_client=leanstral_client,
        spacy_pipeline=spacy_pipeline,
    )
    return SemanticRoundTripMatrix(
        constructors,
        realizers,
        validators=validators,
    )


def load_matrix_cases(path: str | Path) -> tuple[MatrixCase, ...]:
    """Load the benchmark's JSON case array through the strict contracts."""

    import json

    fixture_path = Path(path)
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ContractError("matrix fixture must be a nonempty JSON array")
    return tuple(MatrixCase.from_dict(case) for case in payload)


load_cases = load_matrix_cases


def run_matrix(
    cases: Sequence[MatrixCase],
    constructors: Mapping[str, RoundTripConstructor],
    realizers: Mapping[str, RoundTripRealizer],
    *,
    constructor_configs: Mapping[str, Mapping[str, object]] | None = None,
    realizer_configs: Mapping[str, Mapping[str, object]] | None = None,
    validators: Mapping[str, PostHocValidator] | None = None,
    require_eight_cells: bool = True,
) -> MatrixRunResult:
    """One-call convenience wrapper around :class:`SemanticRoundTripMatrix`."""

    return SemanticRoundTripMatrix(
        constructors,
        realizers,
        constructor_configs=constructor_configs,
        realizer_configs=realizer_configs,
        validators=validators,
        require_eight_cells=require_eight_cells,
    ).run(cases)


__all__ = [
    "SEMANTIC_ROUND_TRIP_MATRIX_INTERFACE",
    "MATRIX_CONSTRUCTOR_IDS",
    "MATRIX_REALIZER_IDS",
    "MATRIX_CONSTRUCTORS",
    "MATRIX_REALIZERS",
    "EXPECTED_CELL_IDS",
    "COPY_NGRAM_WIDTH",
    "COPY_PRECISION_LIMIT",
    "MatrixCase",
    "PostHocValidator",
    "MatrixCoordinateRecord",
    "MatrixCaseRecord",
    "MatrixRunResult",
    "SemanticRoundTripMatrix",
    "MatrixRunner",
    "MatrixCellResult",
    "MatrixCaseResult",
    "source_copy_diagnostics",
    "source_copy_metrics",
    "polarity_diagnostics",
    "default_post_hoc_validators",
    "default_component_registries",
    "default_matrix",
    "load_matrix_cases",
    "load_cases",
    "run_matrix",
]
