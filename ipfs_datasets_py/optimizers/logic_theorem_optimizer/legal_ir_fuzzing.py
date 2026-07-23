"""Metamorphic and differential fuzzing for LegalIR compiler validation.

The fuzzer in this module is intentionally deterministic and dependency-light:
it mutates LegalIR-facing artifacts, recompiles or reprojects the affected
surface, checks the expected metamorphic relation, and records verified
semantic counterexamples as source-copy-safe hard-negative candidates.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Final, Mapping, Optional, Sequence

from ipfs_datasets_py.logic.integration.reasoning.legal_ir_obligations import (
    LegalIRProofObligation,
    generate_legal_ir_proof_obligations,
)

from .legal_ir_grammar_decoder import validate_legal_ir_candidate
from .legal_ir_semantic_metrics import (
    OBLIGATION_EQUIVALENCE,
    PROOF_OBLIGATION_DELTA,
    PROOF_OBLIGATION_DELTA_SCORE,
    STRUCTURAL_EQUIVALENCE,
    evaluate_legal_ir_semantic_equivalence,
)
from .legal_modal_parser import LegalModalParser
from .modal_autoencoder import build_decompiler_structural_learning_target
from .modal_ir import ModalIRDocument


LEGAL_IR_FUZZING_SCHEMA_VERSION: Final = (
    "legal-ir-metamorphic-differential-fuzzing-v1"
)
LEGAL_IR_TRUSTED_NEGATIVE_SCHEMA_VERSION: Final = (
    "legal-ir-fuzzing-trusted-negative-v1"
)

SEMANTICS_PRESERVING: Final = "semantics_preserving"
SEMANTICS_CHANGING: Final = "semantics_changing"

TARGET_TEXT: Final = "text"
TARGET_DETERMINISTIC_IR: Final = "deterministic_ir"
TARGET_LEARNED_IR: Final = "learned_ir"
TARGET_OBLIGATIONS: Final = "obligations"
TARGET_DECOMPILER: Final = "decompiler"

FUZZING_TARGETS: Final[tuple[str, ...]] = (
    TARGET_TEXT,
    TARGET_DETERMINISTIC_IR,
    TARGET_LEARNED_IR,
    TARGET_OBLIGATIONS,
    TARGET_DECOMPILER,
)

_TRUE = frozenset({"1", "accepted", "passed", "proved", "true", "trusted", "verified"})
_MODAL_FORCE = {
    "shall": "obligation",
    "must": "obligation",
    "required": "obligation",
    "requires": "obligation",
    "require": "obligation",
    "may": "permission",
    "authorized": "permission",
    "permitted": "permission",
    "p": "permission",
    "permit": "permission",
    "o": "obligation",
    "obligation": "obligation",
    "shall not": "prohibition",
    "must not": "prohibition",
    "may not": "prohibition",
    "prohibited": "prohibition",
}


def _stable_json(value: Any) -> str:
    return json.dumps(
        _json_ready(value),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return str(value)
        return round(value, 12)
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return [_json_ready(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    return str(value)


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        if isinstance(converted, Mapping):
            return dict(converted)
    return {}


def _sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return list(value)
    return [value]


def _norm(value: Any) -> str:
    text = str(value or "").strip().lower().replace("_", " ")
    text = re.sub(r"[^a-z0-9./:-]+", "_", text)
    return text.strip("_") or "none"


def _force(value: Any) -> str:
    text = " ".join(str(value or "").lower().replace("_", " ").split())
    if "not" in text and any(token in text for token in ("shall", "must", "may")):
        return "prohibition"
    return _MODAL_FORCE.get(text, _MODAL_FORCE.get(_norm(text), _norm(text)))


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    if not union:
        return 1.0
    return round(len(left & right) / len(union), 12)


@dataclass(frozen=True)
class LegalIRFuzzingConfig:
    """Runtime policy for one deterministic LegalIR fuzzing run."""

    seed: int = 0
    targets: tuple[str, ...] = FUZZING_TARGETS
    preserving_similarity_threshold: float = 1.0
    changing_similarity_threshold: float = 0.999999
    store_trusted_negatives: bool = True
    require_verification_for_trusted_negatives: bool = True
    max_counterexample_depth: int = 3

    def __post_init__(self) -> None:
        targets = tuple(dict.fromkeys(str(target) for target in self.targets))
        invalid = tuple(target for target in targets if target not in FUZZING_TARGETS)
        if invalid:
            raise ValueError(f"unsupported LegalIR fuzzing targets: {invalid!r}")
        if not targets:
            raise ValueError("at least one fuzzing target is required")
        object.__setattr__(self, "targets", targets)
        for name in ("preserving_similarity_threshold", "changing_similarity_threshold"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0 or value > 1.0:
                raise ValueError(f"{name} must be finite and between 0 and 1")
            object.__setattr__(self, name, value)
        depth = int(self.max_counterexample_depth)
        if depth < 0 or depth > 8:
            raise ValueError("max_counterexample_depth must be between 0 and 8")
        object.__setattr__(self, "max_counterexample_depth", depth)


@dataclass(frozen=True)
class LegalIRMutation:
    """One metamorphic mutation over a LegalIR-facing artifact."""

    target: str
    relation: str
    operator: str
    original: Any
    mutated: Any
    description: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.target not in FUZZING_TARGETS:
            raise ValueError(f"unsupported mutation target: {self.target!r}")
        if self.relation not in {SEMANTICS_PRESERVING, SEMANTICS_CHANGING}:
            raise ValueError(f"unsupported mutation relation: {self.relation!r}")

    @property
    def mutation_id(self) -> str:
        payload = {
            "metadata": self.metadata,
            "mutated": self.mutated,
            "operator": self.operator,
            "relation": self.relation,
            "target": self.target,
        }
        return f"lir-fuzz-mutation-{_stable_hash(payload)[:24]}"

    @property
    def expected_metric_behavior(self) -> str:
        return "invariant" if self.relation == SEMANTICS_PRESERVING else "changed"

    def to_dict(self, *, include_payloads: bool = True) -> dict[str, Any]:
        payload = {
            "description": self.description,
            "expected_metric_behavior": self.expected_metric_behavior,
            "metadata": _json_ready(self.metadata),
            "mutation_id": self.mutation_id,
            "operator": self.operator,
            "relation": self.relation,
            "target": self.target,
        }
        if include_payloads:
            payload.update(
                {
                    "mutated": _json_ready(self.mutated),
                    "original": _json_ready(self.original),
                }
            )
        else:
            payload.update(
                {
                    "mutated_digest": _stable_hash(self.mutated),
                    "original_digest": _stable_hash(self.original),
                }
            )
        return payload


@dataclass(frozen=True)
class LegalIRSurfaceBundle:
    """All surfaces used for differential comparison for one artifact state."""

    text: str
    deterministic_ir: Mapping[str, Any]
    learned_ir: Mapping[str, Any]
    obligations: tuple[Mapping[str, Any], ...]
    decompiler_output: Mapping[str, Any]

    def surface(self, target: str) -> Any:
        if target == TARGET_TEXT:
            return self.text
        if target == TARGET_DETERMINISTIC_IR:
            return self.deterministic_ir
        if target == TARGET_LEARNED_IR:
            return self.learned_ir
        if target == TARGET_OBLIGATIONS:
            return list(self.obligations)
        if target == TARGET_DECOMPILER:
            return self.decompiler_output
        raise ValueError(f"unsupported target: {target!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "decompiler_output": _json_ready(self.decompiler_output),
            "deterministic_ir": _json_ready(self.deterministic_ir),
            "learned_ir": _json_ready(self.learned_ir),
            "obligations": [_json_ready(item) for item in self.obligations],
            "text_sha256": _text_hash(self.text),
        }


@dataclass(frozen=True)
class TrustedNegativeCandidate:
    """Verified minimal LegalIR non-equivalence candidate for later curricula."""

    candidate_id: str
    source_mutation_id: str
    target: str
    relation: str
    label: str
    minimal_counterexample: Any
    verification: Mapping[str, Any]
    source_text_sha256: str = ""
    mutated_payload_sha256: str = ""
    trusted: bool = True
    training_partition: str = "trusted_negative"
    schema_version: str = LEGAL_IR_TRUSTED_NEGATIVE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "label": self.label,
            "minimal_counterexample": _json_ready(self.minimal_counterexample),
            "mutated_payload_sha256": self.mutated_payload_sha256,
            "relation": self.relation,
            "schema_version": self.schema_version,
            "source_mutation_id": self.source_mutation_id,
            "source_text_sha256": self.source_text_sha256,
            "target": self.target,
            "training_partition": self.training_partition,
            "trusted": self.trusted,
            "verification": _json_ready(self.verification),
        }


@dataclass(frozen=True)
class LegalIRFuzzingResult:
    """Metamorphic and differential result for one mutation."""

    mutation: LegalIRMutation
    semantic_similarity: float
    compiler_similarity: float
    learned_similarity: float
    hammer_obligation_similarity: float
    decompiler_similarity: float
    invariant_holds: bool
    expected_change_detected: bool
    differential_consistent: bool
    verified: bool
    semantic_metrics: Mapping[str, Any]
    differential_metrics: Mapping[str, Any]
    grammar_rejections: tuple[str, ...] = ()
    counterexample: Optional[TrustedNegativeCandidate] = None

    @property
    def passed(self) -> bool:
        if self.mutation.relation == SEMANTICS_PRESERVING:
            return self.invariant_holds and self.differential_consistent
        return self.expected_change_detected and self.verified

    def to_dict(self) -> dict[str, Any]:
        return {
            "compiler_similarity": self.compiler_similarity,
            "counterexample": (
                self.counterexample.to_dict() if self.counterexample is not None else None
            ),
            "decompiler_similarity": self.decompiler_similarity,
            "differential_consistent": self.differential_consistent,
            "differential_metrics": _json_ready(self.differential_metrics),
            "expected_change_detected": self.expected_change_detected,
            "grammar_rejections": list(self.grammar_rejections),
            "hammer_obligation_similarity": self.hammer_obligation_similarity,
            "invariant_holds": self.invariant_holds,
            "learned_similarity": self.learned_similarity,
            "mutation": self.mutation.to_dict(include_payloads=False),
            "passed": self.passed,
            "semantic_metrics": _json_ready(self.semantic_metrics),
            "semantic_similarity": self.semantic_similarity,
            "verified": self.verified,
        }


@dataclass(frozen=True)
class LegalIRFuzzingReport:
    """Complete LegalIR fuzzing report."""

    sample_id: str
    results: tuple[LegalIRFuzzingResult, ...]
    trusted_negative_candidates: tuple[TrustedNegativeCandidate, ...]
    baseline: LegalIRSurfaceBundle
    schema_version: str = LEGAL_IR_FUZZING_SCHEMA_VERSION

    @property
    def mutation_count(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.results)

    @property
    def failed_mutation_ids(self) -> tuple[str, ...]:
        return tuple(
            result.mutation.mutation_id for result in self.results if not result.passed
        )

    @property
    def coverage_by_target(self) -> Mapping[str, Mapping[str, int]]:
        coverage: dict[str, dict[str, int]] = {
            target: {SEMANTICS_PRESERVING: 0, SEMANTICS_CHANGING: 0}
            for target in FUZZING_TARGETS
        }
        for result in self.results:
            coverage[result.mutation.target][result.mutation.relation] += 1
        return coverage

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline": self.baseline.to_dict(),
            "coverage_by_target": _json_ready(self.coverage_by_target),
            "failed_mutation_ids": list(self.failed_mutation_ids),
            "mutation_count": self.mutation_count,
            "passed": self.passed,
            "results": [result.to_dict() for result in self.results],
            "sample_id": self.sample_id,
            "schema_version": self.schema_version,
            "trusted_negative_candidates": [
                candidate.to_dict() for candidate in self.trusted_negative_candidates
            ],
            "trusted_negative_count": len(self.trusted_negative_candidates),
        }


class LegalIRFuzzer:
    """Generate and verify deterministic LegalIR metamorphic mutations."""

    def __init__(
        self,
        *,
        config: Optional[LegalIRFuzzingConfig] = None,
        parser: Optional[LegalModalParser] = None,
    ) -> None:
        self.config = config or LegalIRFuzzingConfig()
        self.parser = parser or LegalModalParser()

    def run(
        self,
        text: str,
        *,
        sample_id: str = "",
        citation: str = "",
        learned_ir: Optional[Mapping[str, Any]] = None,
        decompiler_output: Optional[Mapping[str, Any]] = None,
    ) -> LegalIRFuzzingReport:
        """Run all configured metamorphic and differential fuzz checks."""

        resolved_sample_id = sample_id or f"lir-fuzz-sample-{_text_hash(text)[:16]}"
        baseline = self._bundle_from_text(
            text,
            sample_id=resolved_sample_id,
            citation=citation,
            learned_ir=learned_ir,
            decompiler_output=decompiler_output,
        )
        mutations = self.generate_mutations(baseline)
        results = tuple(
            self.evaluate_mutation(
                baseline,
                mutation,
                sample_id=resolved_sample_id,
                citation=citation,
            )
            for mutation in mutations
            if mutation.target in self.config.targets
        )
        trusted = tuple(
            result.counterexample
            for result in results
            if result.counterexample is not None
        )
        return LegalIRFuzzingReport(
            sample_id=resolved_sample_id,
            results=results,
            trusted_negative_candidates=trusted,
            baseline=baseline,
        )

    def generate_mutations(
        self,
        baseline: LegalIRSurfaceBundle,
    ) -> tuple[LegalIRMutation, ...]:
        """Return deterministic preserving and changing mutations for every target."""

        deterministic = copy.deepcopy(dict(baseline.deterministic_ir))
        learned = copy.deepcopy(dict(baseline.learned_ir))
        obligations = [copy.deepcopy(dict(item)) for item in baseline.obligations]
        decompiler = copy.deepcopy(dict(baseline.decompiler_output))

        mutations: list[LegalIRMutation] = []
        mutations.extend(self._text_mutations(baseline.text))
        mutations.extend(self._deterministic_ir_mutations(deterministic))
        mutations.extend(self._learned_ir_mutations(learned))
        mutations.extend(self._obligation_mutations(obligations))
        mutations.extend(self._decompiler_mutations(decompiler, baseline.text))
        return tuple(
            sorted(
                mutations,
                key=lambda mutation: (
                    FUZZING_TARGETS.index(mutation.target),
                    mutation.relation,
                    mutation.operator,
                    mutation.mutation_id,
                ),
            )
        )

    def evaluate_mutation(
        self,
        baseline: LegalIRSurfaceBundle,
        mutation: LegalIRMutation,
        *,
        sample_id: str = "lir-fuzz-sample",
        citation: str = "",
    ) -> LegalIRFuzzingResult:
        """Evaluate one mutation against metamorphic and differential oracles."""

        mutated = self._bundle_for_mutation(
            baseline,
            mutation,
            sample_id=sample_id,
            citation=citation,
        )
        baseline_summary = _bundle_summary(baseline)
        mutated_summary = _bundle_summary(mutated)
        semantic_similarity = _jaccard(baseline_summary, mutated_summary)
        compiler_similarity = _jaccard(
            _semantic_tokens_for_document(baseline.deterministic_ir),
            _semantic_tokens_for_document(mutated.deterministic_ir),
        )
        learned_similarity = _jaccard(
            _semantic_tokens_for_learned_ir(baseline.learned_ir),
            _semantic_tokens_for_learned_ir(mutated.learned_ir),
        )
        hammer_similarity = _jaccard(
            _semantic_tokens_for_obligations(baseline.obligations),
            _semantic_tokens_for_obligations(mutated.obligations),
        )
        decompiler_similarity = _jaccard(
            _semantic_tokens_for_decompiler(baseline.decompiler_output),
            _semantic_tokens_for_decompiler(mutated.decompiler_output),
        )

        semantic_result = evaluate_legal_ir_semantic_equivalence(
            baseline.surface(mutation.target),
            mutated.surface(mutation.target),
            family=mutation.target,
        )
        semantic_metrics = semantic_result.to_dict()
        differential_metrics = self._differential_metrics(baseline, mutated)
        grammar_rejections = self._grammar_rejections(mutation, mutated)

        invariant_holds = (
            semantic_similarity >= self.config.preserving_similarity_threshold
            and compiler_similarity >= self.config.preserving_similarity_threshold
            and learned_similarity >= self.config.preserving_similarity_threshold
            and hammer_similarity >= self.config.preserving_similarity_threshold
            and decompiler_similarity >= self.config.preserving_similarity_threshold
            and not grammar_rejections
        )
        expected_change_detected = (
            semantic_similarity < self.config.changing_similarity_threshold
            or compiler_similarity < self.config.changing_similarity_threshold
            or learned_similarity < self.config.changing_similarity_threshold
            or hammer_similarity < self.config.changing_similarity_threshold
            or decompiler_similarity < self.config.changing_similarity_threshold
            or bool(grammar_rejections)
        )
        differential_consistent = self._differential_consistent(
            mutation,
            semantic_similarity=semantic_similarity,
            compiler_similarity=compiler_similarity,
            learned_similarity=learned_similarity,
            hammer_similarity=hammer_similarity,
            decompiler_similarity=decompiler_similarity,
            grammar_rejections=grammar_rejections,
        )
        verified = (
            (invariant_holds and mutation.relation == SEMANTICS_PRESERVING)
            or (
                mutation.relation == SEMANTICS_CHANGING
                and expected_change_detected
                and differential_consistent
            )
        )
        counterexample = None
        if self._should_store_counterexample(mutation, verified, expected_change_detected):
            counterexample = self._trusted_negative_candidate(
                baseline,
                mutation,
                semantic_similarity=semantic_similarity,
                differential_metrics=differential_metrics,
                grammar_rejections=grammar_rejections,
            )

        return LegalIRFuzzingResult(
            mutation=mutation,
            semantic_similarity=semantic_similarity,
            compiler_similarity=compiler_similarity,
            learned_similarity=learned_similarity,
            hammer_obligation_similarity=hammer_similarity,
            decompiler_similarity=decompiler_similarity,
            invariant_holds=invariant_holds,
            expected_change_detected=expected_change_detected,
            differential_consistent=differential_consistent,
            verified=verified,
            semantic_metrics=semantic_metrics,
            differential_metrics=differential_metrics,
            grammar_rejections=grammar_rejections,
            counterexample=counterexample,
        )

    def _bundle_from_text(
        self,
        text: str,
        *,
        sample_id: str,
        citation: str = "",
        learned_ir: Optional[Mapping[str, Any]] = None,
        decompiler_output: Optional[Mapping[str, Any]] = None,
    ) -> LegalIRSurfaceBundle:
        document = self.parser.parse(
            text,
            document_id=sample_id,
            citation=citation or None,
        )
        return self._bundle_from_document(
            document,
            text=text,
            learned_ir=learned_ir,
            decompiler_output=decompiler_output,
        )

    def _bundle_from_document(
        self,
        document: ModalIRDocument | Mapping[str, Any],
        *,
        text: str,
        learned_ir: Optional[Mapping[str, Any]] = None,
        obligations: Optional[Sequence[Any]] = None,
        decompiler_output: Optional[Mapping[str, Any]] = None,
    ) -> LegalIRSurfaceBundle:
        deterministic = _document_to_mapping(document)
        obligation_items = tuple(
            _obligation_to_mapping(item)
            for item in (
                obligations
                if obligations is not None
                else generate_legal_ir_proof_obligations(document)
            )
        )
        resolved_learned = (
            copy.deepcopy(dict(learned_ir))
            if learned_ir is not None
            else _learned_ir_from_document(deterministic)
        )
        resolved_decompiler = _decompiler_plan_from_target(
            copy.deepcopy(dict(decompiler_output))
            if decompiler_output is not None
            else build_decompiler_structural_learning_target(document, source_text=text)
        )
        return LegalIRSurfaceBundle(
            text=text,
            deterministic_ir=deterministic,
            learned_ir=resolved_learned,
            obligations=obligation_items,
            decompiler_output=resolved_decompiler,
        )

    def _bundle_for_mutation(
        self,
        baseline: LegalIRSurfaceBundle,
        mutation: LegalIRMutation,
        *,
        sample_id: str,
        citation: str,
    ) -> LegalIRSurfaceBundle:
        if mutation.target == TARGET_TEXT:
            return self._bundle_from_text(
                str(mutation.mutated),
                sample_id=sample_id,
                citation=citation,
            )
        if mutation.target == TARGET_DETERMINISTIC_IR:
            return self._bundle_from_document(
                copy.deepcopy(mutation.mutated),
                text=baseline.text,
            )
        if mutation.target == TARGET_LEARNED_IR:
            return LegalIRSurfaceBundle(
                text=baseline.text,
                deterministic_ir=baseline.deterministic_ir,
                learned_ir=copy.deepcopy(dict(mutation.mutated)),
                obligations=baseline.obligations,
                decompiler_output=baseline.decompiler_output,
            )
        if mutation.target == TARGET_OBLIGATIONS:
            return LegalIRSurfaceBundle(
                text=baseline.text,
                deterministic_ir=baseline.deterministic_ir,
                learned_ir=baseline.learned_ir,
                obligations=tuple(
                    dict(item) for item in _sequence(copy.deepcopy(mutation.mutated))
                ),
                decompiler_output=baseline.decompiler_output,
            )
        if mutation.target == TARGET_DECOMPILER:
            return LegalIRSurfaceBundle(
                text=baseline.text,
                deterministic_ir=baseline.deterministic_ir,
                learned_ir=baseline.learned_ir,
                obligations=baseline.obligations,
                decompiler_output=copy.deepcopy(dict(mutation.mutated)),
            )
        raise ValueError(f"unsupported target: {mutation.target!r}")

    def _text_mutations(self, text: str) -> tuple[LegalIRMutation, ...]:
        preserving = " ".join(text.split())
        changing = _replace_first(
            text,
            (
                (r"\bshall\s+not\b", "may"),
                (r"\bmust\s+not\b", "may"),
                (r"\bshall\b", "may"),
                (r"\bmust\b", "may"),
                (r"\bmay\b", "shall"),
            ),
            fallback=text + " The agency may waive compliance.",
        )
        deadline_changed = re.sub(
            r"\bwithin\s+(\d+)\s+(day|days|month|months|year|years)\b",
            lambda match: f"within {int(match.group(1)) + 30} {match.group(2)}",
            text,
            count=1,
            flags=re.I,
        )
        if deadline_changed == text:
            deadline_changed = changing
        return (
            LegalIRMutation(
                target=TARGET_TEXT,
                relation=SEMANTICS_PRESERVING,
                operator="modal_synonym_whitespace_normalization",
                original=text,
                mutated=preserving,
                description="Normalize whitespace without changing legal semantics.",
            ),
            LegalIRMutation(
                target=TARGET_TEXT,
                relation=SEMANTICS_CHANGING,
                operator="modal_force_flip",
                original=text,
                mutated=changing,
                description="Flip obligation/permission force in the source text.",
            ),
            LegalIRMutation(
                target=TARGET_TEXT,
                relation=SEMANTICS_CHANGING,
                operator="temporal_window_shift",
                original=text,
                mutated=deadline_changed,
                description="Change a temporal compliance window.",
            ),
        )

    def _deterministic_ir_mutations(
        self,
        document: Mapping[str, Any],
    ) -> tuple[LegalIRMutation, ...]:
        preserving = copy.deepcopy(dict(document))
        preserving.setdefault("metadata", {})["fuzz_note"] = "metadata_only"
        changing = copy.deepcopy(dict(document))
        _mutate_first_formula(changing, _flip_formula_operator)
        exception_changed = copy.deepcopy(dict(document))
        _mutate_first_formula(exception_changed, _remove_first_exception)
        return (
            LegalIRMutation(
                target=TARGET_DETERMINISTIC_IR,
                relation=SEMANTICS_PRESERVING,
                operator="deterministic_ir_metadata_noise",
                original=document,
                mutated=preserving,
                description="Add non-semantic metadata to deterministic IR.",
            ),
            LegalIRMutation(
                target=TARGET_DETERMINISTIC_IR,
                relation=SEMANTICS_CHANGING,
                operator="deterministic_ir_operator_flip",
                original=document,
                mutated=changing,
                description="Flip the first formula operator force.",
            ),
            LegalIRMutation(
                target=TARGET_DETERMINISTIC_IR,
                relation=SEMANTICS_CHANGING,
                operator="deterministic_ir_exception_drop",
                original=document,
                mutated=exception_changed,
                description="Drop an exception scope from the first formula.",
            ),
        )

    def _learned_ir_mutations(
        self,
        learned_ir: Mapping[str, Any],
    ) -> tuple[LegalIRMutation, ...]:
        preserving = copy.deepcopy(dict(learned_ir))
        preserving.setdefault("metadata", {})["fuzz_note"] = "metadata_only"
        changing = copy.deepcopy(dict(learned_ir))
        rules = _sequence(changing.get("rules"))
        if rules and isinstance(rules[0], Mapping):
            first = dict(rules[0])
            first["modality"] = _flip_modality(first.get("modality"))
            rules[0] = first
            changing["rules"] = rules
        else:
            changing["rules"] = [
                {"modality": "permission", "subject": "agency", "action": "waive"}
            ]
        source_copy = copy.deepcopy(dict(learned_ir))
        source_copy["source_text"] = "SOURCE_TEXT"
        return (
            LegalIRMutation(
                target=TARGET_LEARNED_IR,
                relation=SEMANTICS_PRESERVING,
                operator="learned_ir_metadata_noise",
                original=learned_ir,
                mutated=preserving,
                description="Add non-semantic learned-guidance metadata.",
            ),
            LegalIRMutation(
                target=TARGET_LEARNED_IR,
                relation=SEMANTICS_CHANGING,
                operator="learned_ir_modality_flip",
                original=learned_ir,
                mutated=changing,
                description="Flip learned-guidance modality.",
            ),
            LegalIRMutation(
                target=TARGET_LEARNED_IR,
                relation=SEMANTICS_CHANGING,
                operator="learned_ir_source_copy_placeholder",
                original=learned_ir,
                mutated=source_copy,
                description="Inject a learned placeholder that grammar guards must reject.",
            ),
        )

    def _obligation_mutations(
        self,
        obligations: Sequence[Mapping[str, Any]],
    ) -> tuple[LegalIRMutation, ...]:
        original = [dict(item) for item in obligations]
        preserving = copy.deepcopy(original)
        if preserving:
            hints = list(reversed(_sequence(preserving[0].get("premise_hints"))))
            preserving[0]["premise_hints"] = hints
            preserving[0].setdefault("metadata", {})["fuzz_note"] = "hint_order_only"
        changing = copy.deepcopy(original)
        if changing:
            changing[0]["statement"] = (
                str(changing[0].get("statement") or "") + "_mutated_counterexample"
            )
        dropped = copy.deepcopy(original[1:] if len(original) > 1 else [])
        return (
            LegalIRMutation(
                target=TARGET_OBLIGATIONS,
                relation=SEMANTICS_PRESERVING,
                operator="obligation_premise_hint_reorder",
                original=original,
                mutated=preserving,
                description="Reorder premise hints without changing proof obligation identity.",
            ),
            LegalIRMutation(
                target=TARGET_OBLIGATIONS,
                relation=SEMANTICS_CHANGING,
                operator="obligation_statement_mutation",
                original=original,
                mutated=changing,
                description="Change a Hammer obligation statement.",
            ),
            LegalIRMutation(
                target=TARGET_OBLIGATIONS,
                relation=SEMANTICS_CHANGING,
                operator="obligation_drop",
                original=original,
                mutated=dropped,
                description="Drop an obligation from the Hammer surface.",
            ),
        )

    def _decompiler_mutations(
        self,
        decompiler: Mapping[str, Any],
        text: str,
    ) -> tuple[LegalIRMutation, ...]:
        preserving = copy.deepcopy(dict(decompiler))
        preserving.setdefault("metadata", {})["fuzz_note"] = "metadata_only"
        changing = copy.deepcopy(dict(decompiler))
        features = _sequence(changing.get("feature_targets"))
        changing["feature_targets"] = features[1:] if features else ["missing=feature"]
        unsafe = copy.deepcopy(dict(decompiler))
        unsafe["source_copy_policy"] = "raw_source"
        unsafe["steps"] = [{"op": "emit_text", "surface": text}]
        unsafe["target_view"] = "deontic.ir"
        return (
            LegalIRMutation(
                target=TARGET_DECOMPILER,
                relation=SEMANTICS_PRESERVING,
                operator="decompiler_metadata_noise",
                original=decompiler,
                mutated=preserving,
                description="Add non-semantic decompiler metadata.",
            ),
            LegalIRMutation(
                target=TARGET_DECOMPILER,
                relation=SEMANTICS_CHANGING,
                operator="decompiler_feature_drop",
                original=decompiler,
                mutated=changing,
                description="Remove a structural decompiler feature target.",
            ),
            LegalIRMutation(
                target=TARGET_DECOMPILER,
                relation=SEMANTICS_CHANGING,
                operator="decompiler_source_copy_violation",
                original=decompiler,
                mutated=unsafe,
                description="Inject an unsafe source-copy decompiler output.",
            ),
        )

    def _differential_metrics(
        self,
        baseline: LegalIRSurfaceBundle,
        mutated: LegalIRSurfaceBundle,
    ) -> dict[str, Any]:
        compiler_learned = evaluate_legal_ir_semantic_equivalence(
            mutated.deterministic_ir,
            mutated.learned_ir,
            family="compiler_vs_learned",
        )
        compiler_decompiler = evaluate_legal_ir_semantic_equivalence(
            mutated.deterministic_ir,
            mutated.decompiler_output,
            family="compiler_vs_decompiler",
        )
        hammer_delta = evaluate_legal_ir_semantic_equivalence(
            baseline.obligations,
            mutated.obligations,
            family="hammer_obligations",
        )
        baseline_round_trip = evaluate_legal_ir_semantic_equivalence(
            baseline.deterministic_ir,
            baseline.decompiler_output,
            family="baseline_round_trip",
        )
        mutated_round_trip = evaluate_legal_ir_semantic_equivalence(
            mutated.deterministic_ir,
            mutated.decompiler_output,
            family="mutated_round_trip",
        )
        return {
            "baseline_round_trip": baseline_round_trip.to_dict(),
            "compiler_vs_decompiler": compiler_decompiler.to_dict(),
            "compiler_vs_learned_guidance": compiler_learned.to_dict(),
            "hammer_obligation_delta": hammer_delta.to_dict(),
            "mutated_round_trip": mutated_round_trip.to_dict(),
            "proof_obligation_delta": hammer_delta.raw_deltas.get(
                PROOF_OBLIGATION_DELTA, 0.0
            ),
            "round_trip_structural_delta": round(
                mutated_round_trip.scores.get(STRUCTURAL_EQUIVALENCE, 0.0)
                - baseline_round_trip.scores.get(STRUCTURAL_EQUIVALENCE, 0.0),
                12,
            ),
        }

    def _grammar_rejections(
        self,
        mutation: LegalIRMutation,
        mutated: LegalIRSurfaceBundle,
    ) -> tuple[str, ...]:
        if mutation.target == TARGET_LEARNED_IR:
            family = str(_as_mapping(mutated.learned_ir).get("family") or "deontic")
            result = validate_legal_ir_candidate(
                mutated.learned_ir,
                family=family,
                source_text=mutated.text,
            )
            return tuple(result.rejection_reason_names)
        if mutation.target == TARGET_DECOMPILER:
            result = validate_legal_ir_candidate(
                mutated.decompiler_output,
                family="decompiler",
                source_text=mutated.text,
            )
            return tuple(result.rejection_reason_names)
        return ()

    def _differential_consistent(
        self,
        mutation: LegalIRMutation,
        *,
        semantic_similarity: float,
        compiler_similarity: float,
        learned_similarity: float,
        hammer_similarity: float,
        decompiler_similarity: float,
        grammar_rejections: Sequence[str],
    ) -> bool:
        if mutation.relation == SEMANTICS_PRESERVING:
            return (
                semantic_similarity >= self.config.preserving_similarity_threshold
                and compiler_similarity >= self.config.preserving_similarity_threshold
                and learned_similarity >= self.config.preserving_similarity_threshold
                and hammer_similarity >= self.config.preserving_similarity_threshold
                and decompiler_similarity >= self.config.preserving_similarity_threshold
                and not grammar_rejections
            )
        changed_surfaces = sum(
            value < self.config.changing_similarity_threshold
            for value in (
                semantic_similarity,
                compiler_similarity,
                learned_similarity,
                hammer_similarity,
                decompiler_similarity,
            )
        )
        if grammar_rejections:
            changed_surfaces += 1
        if mutation.target in {TARGET_LEARNED_IR, TARGET_OBLIGATIONS, TARGET_DECOMPILER}:
            return changed_surfaces >= 1
        return changed_surfaces >= 2

    def _should_store_counterexample(
        self,
        mutation: LegalIRMutation,
        verified: bool,
        expected_change_detected: bool,
    ) -> bool:
        if not self.config.store_trusted_negatives:
            return False
        if mutation.relation != SEMANTICS_CHANGING:
            return False
        if not expected_change_detected:
            return False
        return verified or not self.config.require_verification_for_trusted_negatives

    def _trusted_negative_candidate(
        self,
        baseline: LegalIRSurfaceBundle,
        mutation: LegalIRMutation,
        *,
        semantic_similarity: float,
        differential_metrics: Mapping[str, Any],
        grammar_rejections: Sequence[str],
    ) -> TrustedNegativeCandidate:
        predicate = _negative_predicate_for_mutation(
            mutation,
            baseline=baseline,
            fuzzer=self,
            semantic_threshold=self.config.changing_similarity_threshold,
        )
        minimal = minimize_legal_ir_counterexample(
            mutation.mutated,
            predicate,
            max_depth=self.config.max_counterexample_depth,
        )
        sanitized = _sanitize_counterexample(minimal, source_text=baseline.text)
        verification = {
            "differential_metrics": _json_ready(differential_metrics),
            "grammar_rejections": list(grammar_rejections),
            "semantic_similarity": semantic_similarity,
            "verified": True,
            "verified_by": [
                "metamorphic_metric_oracle",
                "deterministic_compiler",
                "learned_guidance_projection",
                "hammer_obligation_delta",
                "decompiler_round_trip",
            ],
        }
        candidate_payload = {
            "minimal": sanitized,
            "mutation_id": mutation.mutation_id,
            "verification": verification,
        }
        return TrustedNegativeCandidate(
            candidate_id=f"lir-fuzz-negative-{_stable_hash(candidate_payload)[:24]}",
            source_mutation_id=mutation.mutation_id,
            target=mutation.target,
            relation=mutation.relation,
            label="semantic_non_equivalence",
            minimal_counterexample=sanitized,
            verification=verification,
            source_text_sha256=_text_hash(baseline.text),
            mutated_payload_sha256=_stable_hash(mutation.mutated),
        )


def run_legal_ir_metamorphic_fuzzing(
    text: str,
    *,
    sample_id: str = "",
    citation: str = "",
    learned_ir: Optional[Mapping[str, Any]] = None,
    decompiler_output: Optional[Mapping[str, Any]] = None,
    config: Optional[LegalIRFuzzingConfig] = None,
) -> LegalIRFuzzingReport:
    """Convenience API for one LegalIR fuzzing run."""

    return LegalIRFuzzer(config=config).run(
        text,
        sample_id=sample_id,
        citation=citation,
        learned_ir=learned_ir,
        decompiler_output=decompiler_output,
    )


def minimize_legal_ir_counterexample(
    value: Any,
    predicate: Callable[[Any], bool],
    *,
    max_depth: int = 3,
) -> Any:
    """Greedily minimize a payload while preserving a verified predicate."""

    candidate = copy.deepcopy(value)
    if not predicate(candidate):
        return candidate
    return _minimize(candidate, predicate, depth=max(0, int(max_depth)))


def _minimize(value: Any, predicate: Callable[[Any], bool], *, depth: int) -> Any:
    if depth <= 0:
        return value
    if isinstance(value, Mapping):
        candidate = copy.deepcopy(dict(value))
        for key in list(candidate):
            if len(candidate) <= 1:
                break
            trial = copy.deepcopy(candidate)
            trial.pop(key, None)
            if predicate(trial):
                candidate = trial
        for key in list(candidate):
            child = candidate[key]
            minimized = _minimize(
                child,
                lambda child_trial, selected_key=key: predicate(
                    {**candidate, selected_key: child_trial}
                ),
                depth=depth - 1,
            )
            candidate[key] = minimized
        return candidate
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        candidate = list(copy.deepcopy(value))
        index = 0
        while index < len(candidate):
            if len(candidate) <= 1:
                break
            trial = candidate[:index] + candidate[index + 1 :]
            if predicate(trial):
                candidate = trial
            else:
                index += 1
        for index, child in enumerate(list(candidate)):
            minimized = _minimize(
                child,
                lambda child_trial, selected_index=index: predicate(
                    [
                        child_trial if item_index == selected_index else item
                        for item_index, item in enumerate(candidate)
                    ]
                ),
                depth=depth - 1,
            )
            candidate[index] = minimized
        return candidate
    return value


def _negative_predicate_for_mutation(
    mutation: LegalIRMutation,
    *,
    baseline: LegalIRSurfaceBundle,
    fuzzer: LegalIRFuzzer,
    semantic_threshold: float,
) -> Callable[[Any], bool]:
    def predicate(candidate: Any) -> bool:
        candidate_mutation = LegalIRMutation(
            target=mutation.target,
            relation=mutation.relation,
            operator=mutation.operator,
            original=mutation.original,
            mutated=candidate,
            description=mutation.description,
            metadata=mutation.metadata,
        )
        mutated_bundle = fuzzer._bundle_for_mutation(
            baseline,
            candidate_mutation,
            sample_id=str(_as_mapping(baseline.deterministic_ir).get("document_id") or "lir-fuzz-sample"),
            citation=str(_as_mapping(baseline.deterministic_ir).get("metadata", {}).get("citation") or ""),
        )
        return (
            _jaccard(_bundle_summary(baseline), _bundle_summary(mutated_bundle))
            < semantic_threshold
            or bool(fuzzer._grammar_rejections(candidate_mutation, mutated_bundle))
        )

    return predicate


def _replace_first(
    text: str,
    replacements: Sequence[tuple[str, str]],
    *,
    fallback: str,
) -> str:
    for pattern, replacement in replacements:
        changed = re.sub(pattern, replacement, text, count=1, flags=re.I)
        if changed != text:
            return changed
    return fallback


def _document_to_mapping(document: ModalIRDocument | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(document, ModalIRDocument):
        return document.to_dict()
    return copy.deepcopy(dict(document))


def _obligation_to_mapping(obligation: Any) -> dict[str, Any]:
    if isinstance(obligation, LegalIRProofObligation):
        return obligation.to_dict()
    return copy.deepcopy(_as_mapping(obligation))


def _learned_ir_from_document(document: Mapping[str, Any]) -> dict[str, Any]:
    rules: list[dict[str, Any]] = []
    formulas = _sequence(document.get("formulas"))
    for formula in formulas:
        formula_map = _as_mapping(formula)
        operator = _as_mapping(formula_map.get("operator"))
        predicate = _as_mapping(formula_map.get("predicate"))
        arguments = _sequence(predicate.get("arguments"))
        modality = _force(operator.get("label") or operator.get("symbol"))
        if modality not in {"obligation", "permission", "prohibition", "duty", "right"}:
            continue
        rules.append(
            {
                "action": _norm(predicate.get("name") or "predicate"),
                "arguments": [_norm(item) for item in arguments],
                "conditions": [
                    _norm(item) for item in _sequence(formula_map.get("conditions"))
                ],
                "exceptions": [
                    _norm(item) for item in _sequence(formula_map.get("exceptions"))
                ],
                "formula_id": str(formula_map.get("formula_id") or ""),
                "modality": modality,
                "subject": _norm(predicate.get("role") or "legal_actor"),
            }
        )
    if not rules:
        rules.append(
            {
                "action": "no_modal_formula",
                "modality": "none",
                "subject": "document",
            }
        )
    return {
        "family": "deontic",
        "rules": rules,
        "schema_version": "legal-ir-learned-guidance-fuzz-projection-v1",
    }


def _decompiler_plan_from_target(target: Mapping[str, Any]) -> dict[str, Any]:
    plan = copy.deepcopy(dict(target))
    plan.setdefault("family", "decompiler")
    plan.setdefault("target_view", "deontic.ir")
    plan.setdefault("source_copy_policy", "hash_only")
    plan.setdefault("steps", [{"op": "emit_structural_summary", "slot": "formula_targets"}])
    return plan


def _bundle_summary(bundle: LegalIRSurfaceBundle) -> frozenset[str]:
    return frozenset(
        {
            *(f"compiler:{item}" for item in _semantic_tokens_for_document(bundle.deterministic_ir)),
            *(f"learned:{item}" for item in _semantic_tokens_for_learned_ir(bundle.learned_ir)),
            *(f"obligation:{item}" for item in _semantic_tokens_for_obligations(bundle.obligations)),
            *(f"decompiler:{item}" for item in _semantic_tokens_for_decompiler(bundle.decompiler_output)),
        }
    )


def _semantic_tokens_for_document(document: Any) -> frozenset[str]:
    source = _as_mapping(document)
    tokens: set[str] = set()
    for formula in _sequence(source.get("formulas")):
        formula_map = _as_mapping(formula)
        operator = _as_mapping(formula_map.get("operator"))
        predicate = _as_mapping(formula_map.get("predicate"))
        tokens.add(
            "formula:"
            + "|".join(
                (
                    _force(operator.get("symbol") or operator.get("label")),
                    _norm(predicate.get("name")),
                    _norm(predicate.get("role")),
                    ",".join(_norm(item) for item in _sequence(predicate.get("arguments"))),
                    ",".join(_norm(item) for item in _sequence(formula_map.get("conditions"))),
                    ",".join(_norm(item) for item in _sequence(formula_map.get("exceptions"))),
                )
            )
        )
    frame_logic = _as_mapping(source.get("frame_logic"))
    for triple in _sequence(frame_logic.get("triples")):
        triple_map = _as_mapping(triple)
        tokens.add(
            "triple:"
            + "|".join(
                (
                    _norm(triple_map.get("subject")),
                    _norm(triple_map.get("predicate") or triple_map.get("relation")),
                    _norm(triple_map.get("object")),
                )
            )
        )
    return frozenset(tokens)


def _semantic_tokens_for_learned_ir(learned_ir: Any) -> frozenset[str]:
    source = _as_mapping(learned_ir)
    tokens: set[str] = set()
    for rule in _sequence(source.get("rules")):
        rule_map = _as_mapping(rule)
        tokens.add(
            "rule:"
            + "|".join(
                (
                    _force(rule_map.get("modality") or rule_map.get("operator")),
                    _norm(rule_map.get("subject") or rule_map.get("actor")),
                    _norm(rule_map.get("action") or rule_map.get("predicate")),
                    ",".join(_norm(item) for item in _sequence(rule_map.get("conditions"))),
                    ",".join(_norm(item) for item in _sequence(rule_map.get("exceptions"))),
                )
            )
        )
    for counterexample in _sequence(source.get("counterexamples")):
        tokens.add("counterexample:" + _stable_hash(counterexample)[:16])
    return frozenset(tokens)


def _semantic_tokens_for_obligations(obligations: Any) -> frozenset[str]:
    tokens: set[str] = set()
    for obligation in _sequence(obligations):
        item = _as_mapping(obligation)
        statement = str(item.get("statement") or "")
        if statement.endswith("_mutated_counterexample"):
            statement = statement.removesuffix("_mutated_counterexample")
            mutation_marker = "mutated"
        else:
            mutation_marker = "canonical"
        tokens.add(
            "obligation:"
            + "|".join(
                (
                    _norm(item.get("kind")),
                    _norm(item.get("legal_ir_view")),
                    _norm(item.get("logic_family")),
                    _norm(statement),
                    mutation_marker,
                )
            )
        )
    return frozenset(tokens)


def _semantic_tokens_for_decompiler(decompiler: Any) -> frozenset[str]:
    source = _as_mapping(decompiler)
    tokens: set[str] = set()
    for feature in _sequence(source.get("feature_targets")):
        tokens.add("feature:" + _norm(feature))
    for formula in _sequence(source.get("formula_targets")):
        formula_map = _as_mapping(formula)
        tokens.add("formula_target:" + _stable_hash(formula_map)[:20])
    summary = _as_mapping(source.get("structural_summary"))
    for key, value in summary.items():
        tokens.add(f"summary:{_norm(key)}={_norm(value)}")
    policy = str(source.get("source_copy_policy") or "").lower()
    if policy and policy not in {"hash_only", "span_hash_only", "citation_only", "no_source_text"}:
        tokens.add(f"unsafe_source_copy_policy:{_norm(policy)}")
    for step in _sequence(source.get("steps")):
        step_map = _as_mapping(step)
        if step_map:
            tokens.add("step:" + _norm(step_map.get("op") or step_map.get("operation")))
    return frozenset(tokens)


def _mutate_first_formula(document: dict[str, Any], mutator: Callable[[dict[str, Any]], None]) -> None:
    formulas = _sequence(document.get("formulas"))
    if formulas and isinstance(formulas[0], Mapping):
        first = copy.deepcopy(dict(formulas[0]))
        mutator(first)
        formulas[0] = first
        document["formulas"] = formulas


def _flip_formula_operator(formula: dict[str, Any]) -> None:
    operator = dict(_as_mapping(formula.get("operator")))
    operator["symbol"] = _flip_operator(operator.get("symbol"))
    operator["label"] = operator["symbol"]
    formula["operator"] = operator


def _remove_first_exception(formula: dict[str, Any]) -> None:
    exceptions = _sequence(formula.get("exceptions"))
    if exceptions:
        formula["exceptions"] = exceptions[1:]
    else:
        formula["exceptions"] = ["new_exception_scope"]


def _flip_operator(value: Any) -> str:
    force = _force(value)
    if force == "permission":
        return "shall"
    if force == "prohibition":
        return "may"
    return "may"


def _flip_modality(value: Any) -> str:
    force = _force(value)
    if force == "permission":
        return "obligation"
    if force == "prohibition":
        return "permission"
    return "permission"


def _sanitize_counterexample(value: Any, *, source_text: str) -> Any:
    normalized_source = " ".join(source_text.lower().split())

    def visit(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {
                str(key): visit(child)
                for key, child in sorted(item.items(), key=lambda pair: str(pair[0]))
            }
        if isinstance(item, Sequence) and not isinstance(item, (bytes, bytearray, str)):
            return [visit(child) for child in item]
        if isinstance(item, str):
            normalized = " ".join(item.lower().split())
            if (
                normalized_source
                and len(normalized.split()) >= 6
                and (
                    normalized in normalized_source
                    or normalized_source in normalized
                )
            ):
                return {
                    "redacted": True,
                    "sha256": _text_hash(item),
                    "source_copy_policy": "hash_only",
                }
            if len(item) > 512:
                return {
                    "redacted": True,
                    "sha256": _text_hash(item),
                    "source_copy_policy": "hash_only",
                }
            return item
        return item

    return visit(value)


__all__ = [
    "FUZZING_TARGETS",
    "LEGAL_IR_FUZZING_SCHEMA_VERSION",
    "LEGAL_IR_TRUSTED_NEGATIVE_SCHEMA_VERSION",
    "SEMANTICS_CHANGING",
    "SEMANTICS_PRESERVING",
    "TARGET_DECOMPILER",
    "TARGET_DETERMINISTIC_IR",
    "TARGET_LEARNED_IR",
    "TARGET_OBLIGATIONS",
    "TARGET_TEXT",
    "LegalIRFuzzer",
    "LegalIRFuzzingConfig",
    "LegalIRFuzzingReport",
    "LegalIRFuzzingResult",
    "LegalIRMutation",
    "LegalIRSurfaceBundle",
    "TrustedNegativeCandidate",
    "minimize_legal_ir_counterexample",
    "run_legal_ir_metamorphic_fuzzing",
]
