"""Typed constrained decoding for LegalIR candidates.

The learned LegalIR heads are allowed to rank candidate productions, but they
must not receive metric reward for output that a deterministic compiler could
never consume.  This module validates decoded LegalIR payloads against compact
typed grammars before semantic metrics are scored.  It is intentionally
dependency-free and JSON-shape based so it can guard adapter outputs,
autoencoder targets, and rollout artifacts uniformly.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Optional

from .legal_ir_family_evaluator import canonical_legal_ir_evaluation_family


LEGAL_IR_GRAMMAR_DECODER_SCHEMA_VERSION: Final = "legal-ir-typed-grammar-decoder-v1"
LEGAL_IR_CONSTRAINED_DECODER_SCHEMA: Final = "IRConstrainedDecoder@1"
LEGAL_IR_CONSTRAINED_DECODER_INTERFACE: Final = (
    "proof-grounded-ir-learning/constrained-decoder/v1"
)
LEGAL_IR_MAX_BEAM_WIDTH: Final = 16
LEGAL_IR_MAX_DECODE_STEPS: Final = 64
LEGAL_IR_CONSTRAINT_MASK_NAMES: Final[tuple[str, ...]] = (
    "valid_token",
    "grammar",
    "binder",
    "type",
    "family",
)
LEGAL_IR_DECODE_FALLBACKS: Final[tuple[str, ...]] = (
    "reject",
    "eos",
    "gold_if_admitted",
)
LEGAL_IR_FROZEN_TOKENIZER_SCHEMA_VERSION: Final = "legal-ir-frozen-tokenizer-v1"
LEGAL_IR_FROZEN_VOCABULARY_SCHEMA: Final = "IRFrozenTokenizerVocabulary@1"
LEGAL_IR_FROZEN_TOKENIZER_INTERFACE: Final = (
    "proof-grounded-ir-learning/canonical-frozen-tokenizer/v1"
)
LEGAL_IR_IDENTIFIER_BUCKET_COUNT: Final = 32
LEGAL_IR_CANONICAL_VOCABULARY_SIZE: Final = 143
LEGAL_IR_CANONICAL_VOCABULARY_CID: Final = (
    "sha256:8782ea363f422557c7a1f62442fe376fb6586f90a679bebb4ba60824de425c1b"
)
LEGAL_IR_TOKEN_CLASSES: Final[tuple[str, ...]] = (
    "padding",
    "special",
    "binder",
    "operator",
    "type",
    "family",
    "proof",
    "tactic",
    "source",
    "identifier",
    "production",
    "source_surface",
)
LEGAL_IR_CLOSED_TOKEN_CLASSES: Final[frozenset[str]] = frozenset(
    {
        "padding",
        "special",
        "binder",
        "operator",
        "type",
        "family",
        "proof",
        "tactic",
        "source",
        "production",
    }
)
LEGAL_IR_GRAMMAR_FAMILIES: Final[tuple[str, ...]] = (
    "deontic",
    "frame_logic",
    "tdfol",
    "knowledge_graphs",
    "cec",
    "external_provers",
    "decompiler",
    "temporal",
    "provenance",
)

_FAMILY_ALIASES: Final[Mapping[str, str]] = {
    "deontic": "deontic",
    "deontic_ir": "deontic",
    "deontic.ir": "deontic",
    "frame": "frame_logic",
    "frame_logic": "frame_logic",
    "flogic": "frame_logic",
    "modal.frame_logic": "frame_logic",
    "tdfol": "tdfol",
    "tdfol.prover": "tdfol",
    "kg": "knowledge_graphs",
    "knowledge_graph": "knowledge_graphs",
    "knowledge_graphs": "knowledge_graphs",
    "knowledge_graphs.neo4j_compat": "knowledge_graphs",
    "cec": "cec",
    "cec.native": "cec",
    "external_prover": "external_provers",
    "external_provers": "external_provers",
    "prover": "external_provers",
    "decompiler": "decompiler",
    "decompiler_plan": "decompiler",
    "temporal": "temporal",
    "temporal_logic": "temporal",
    "provenance": "provenance",
}

_PLACEHOLDER_RE: Final = re.compile(
    r"(\{\{[^}]*\}\}|<[^>]*(?:source|placeholder|todo|copy)[^>]*>|"
    r"\b(?:todo|tbd|placeholder|source_text|raw_source|copy_source|lorem ipsum)\b|"
    r"__[^_]*(?:source|placeholder|todo)[^_]*__)",
    re.IGNORECASE,
)
_SOURCE_TEXT_FIELD_RE: Final = re.compile(
    r"^(?:raw_source|source_text|copied_text|verbatim_text|source_copy)$",
    re.IGNORECASE,
)
_IDENT_RE: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]*$")


@dataclass(frozen=True, slots=True)
class LegalIRProductionSpec:
    """One typed production admitted by a LegalIR family grammar."""

    name: str
    family: str
    output_type: str
    required_fields: tuple[str, ...]
    optional_fields: tuple[str, ...] = ()
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "family": self.family,
            "name": self.name,
            "optional_fields": list(self.optional_fields),
            "output_type": self.output_type,
            "required_fields": list(self.required_fields),
        }


@dataclass(frozen=True, slots=True)
class LegalIRGrammarRejection:
    """Structured reason for rejecting a candidate or production."""

    reason: str
    path: str = "$"
    family: str = "unscoped"
    production: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "detail": self.detail,
            "family": self.family,
            "path": self.path,
            "production": self.production,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class LegalIRGrammarValidation:
    """Validation result for one candidate IR object."""

    accepted: bool
    family: str
    candidate_ir: Any
    rejection_reasons: tuple[LegalIRGrammarRejection, ...] = ()
    selected_productions: tuple[str, ...] = ()
    masked_productions: tuple[str, ...] = ()
    schema_version: str = LEGAL_IR_GRAMMAR_DECODER_SCHEMA_VERSION

    @property
    def rejection_reason_names(self) -> tuple[str, ...]:
        return tuple(reason.reason for reason in self.rejection_reasons)

    @property
    def syntactic_validity_success_rate(self) -> float:
        return 1.0 if self.accepted else 0.0

    @property
    def source_copy_placeholder_penalty(self) -> float:
        return (
            1.0
            if any(
                reason.reason in {"source_copy_placeholder", "raw_source_copy_field"}
                for reason in self.rejection_reasons
            )
            else 0.0
        )

    def metrics(self) -> dict[str, float]:
        rejection_count = float(len(self.rejection_reasons))
        invalid = 0.0 if self.accepted else 1.0
        values: dict[str, float] = {
            "legal_ir_grammar_accepted": 1.0 if self.accepted else 0.0,
            "legal_ir_grammar_invalid_production_penalty": invalid,
            "legal_ir_grammar_rejection_count": rejection_count,
            "legal_ir_grammar_rejection_ratio": invalid,
            "legal_ir_grammar_source_copy_placeholder_penalty": (
                self.source_copy_placeholder_penalty
            ),
            "legal_ir_grammar_syntactic_validity_success_rate": (
                self.syntactic_validity_success_rate
            ),
        }
        for reason in self.rejection_reasons:
            values[f"legal_ir_grammar_rejection_reason_{_metric_slug(reason.reason)}"] = 1.0
        return values

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "candidate_digest": _stable_digest(self.candidate_ir),
            "family": self.family,
            "masked_productions": list(self.masked_productions),
            "metrics": self.metrics(),
            "rejection_reasons": [reason.to_dict() for reason in self.rejection_reasons],
            "schema_version": self.schema_version,
            "selected_productions": list(self.selected_productions),
        }


@dataclass(frozen=True, slots=True)
class ConstrainedLegalIRDecode:
    """Result of masking and selecting from scored LegalIR productions."""

    accepted: bool
    family: str
    decoded_ir: Any
    selected_production: str = ""
    selected_score: float = 0.0
    valid_scores: Mapping[str, float] = field(default_factory=dict)
    masked_scores: Mapping[str, float] = field(default_factory=dict)
    validation: LegalIRGrammarValidation = field(
        default_factory=lambda: LegalIRGrammarValidation(
            accepted=False,
            family="unscoped",
            candidate_ir=None,
            rejection_reasons=(LegalIRGrammarRejection(reason="no_candidate", family="unscoped"),),
        )
    )
    schema_version: str = LEGAL_IR_GRAMMAR_DECODER_SCHEMA_VERSION

    @property
    def rejection_reasons(self) -> tuple[LegalIRGrammarRejection, ...]:
        return self.validation.rejection_reasons

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "decoded_ir": self.decoded_ir if self.accepted else None,
            "family": self.family,
            "masked_scores": {
                str(name): round(float(score), 12)
                for name, score in sorted(self.masked_scores.items())
            },
            "rejection_reasons": [reason.to_dict() for reason in self.rejection_reasons],
            "schema_version": self.schema_version,
            "selected_production": self.selected_production,
            "selected_score": round(float(self.selected_score), 12),
            "valid_scores": {
                str(name): round(float(score), 12)
                for name, score in sorted(self.valid_scores.items())
            },
            "validation": self.validation.to_dict(),
        }


class LegalIRGrammarDecoder:
    """Validate and decode LegalIR candidates with family-specific grammars."""

    def __init__(
        self,
        *,
        production_specs: Optional[Sequence[LegalIRProductionSpec]] = None,
        tokenizer: Optional["LegalIRFrozenTokenizer"] = None,
    ) -> None:
        specs = tuple(production_specs or default_legal_ir_production_specs())
        self.production_specs: dict[str, LegalIRProductionSpec] = {
            spec.name: spec for spec in specs
        }
        self._frozen_tokenizer = tokenizer
        self.productions_by_family: dict[str, tuple[str, ...]] = {}
        for spec in specs:
            family = canonical_legal_ir_grammar_family(spec.family)
            self.productions_by_family.setdefault(family, ())
            self.productions_by_family[family] = (
                *self.productions_by_family[family],
                spec.name,
            )

    def validate(
        self,
        candidate_ir: Any,
        *,
        family: str = "",
        source_text: str = "",
        production: str = "",
    ) -> LegalIRGrammarValidation:
        family_name = infer_legal_ir_grammar_family(candidate_ir, family=family)
        candidate = _mapping_or_sequence(candidate_ir)
        rejections: list[LegalIRGrammarRejection] = []

        if candidate is None:
            rejections.append(
                LegalIRGrammarRejection(
                    reason="candidate_not_structured",
                    family=family_name,
                    production=production,
                    detail=type(candidate_ir).__name__,
                )
            )
            return _validation(candidate_ir, family_name, rejections, production)

        rejections.extend(
            _source_copy_rejections(
                candidate,
                source_text=source_text,
                family=family_name,
                production=production,
            )
        )
        family_validator = _FAMILY_VALIDATORS.get(family_name)
        if family_validator is None:
            rejections.append(
                LegalIRGrammarRejection(
                    reason="unsupported_family",
                    family=family_name,
                    production=production,
                )
            )
        else:
            rejections.extend(family_validator(candidate, family_name, production))
        return _validation(candidate_ir, family_name, rejections, production)

    def mask_invalid_productions(
        self,
        scored_productions: Mapping[str, Any] | Sequence[Any],
        *,
        family: str = "",
        source_text: str = "",
        context: Optional[Mapping[str, Any]] = None,
    ) -> ConstrainedLegalIRDecode:
        """Remove invalid productions before downstream metrics see them."""

        rows = _production_rows(scored_productions, context=context)
        valid_scores: dict[str, float] = {}
        masked_scores: dict[str, float] = {}
        validations: dict[str, LegalIRGrammarValidation] = {}
        for row in rows:
            name = row["name"]
            score = row["score"]
            output = row.get("output")
            row_family = row.get("family") or family
            validation = self.validate(
                output,
                family=str(row_family or ""),
                source_text=source_text,
                production=name,
            )
            validations[name] = validation
            if validation.accepted:
                valid_scores[name] = score
            else:
                masked_scores[name] = score

        if valid_scores:
            selected = max(valid_scores, key=lambda item: (valid_scores[item], item))
            validation = validations[selected]
            return ConstrainedLegalIRDecode(
                accepted=True,
                family=validation.family,
                decoded_ir=validation.candidate_ir,
                selected_production=selected,
                selected_score=valid_scores[selected],
                valid_scores=valid_scores,
                masked_scores=masked_scores,
                validation=validation,
            )

        reasons: list[LegalIRGrammarRejection] = []
        selected_family = canonical_legal_ir_grammar_family(family or "decompiler")
        for validation in validations.values():
            selected_family = validation.family
            reasons.extend(validation.rejection_reasons)
        if not reasons:
            reasons.append(
                LegalIRGrammarRejection(
                    reason="no_productions",
                    family=selected_family,
                )
            )
        validation = LegalIRGrammarValidation(
            accepted=False,
            family=selected_family,
            candidate_ir=None,
            rejection_reasons=tuple(_dedupe_rejections(reasons)),
            masked_productions=tuple(sorted(masked_scores)),
        )
        return ConstrainedLegalIRDecode(
            accepted=False,
            family=selected_family,
            decoded_ir=None,
            valid_scores={},
            masked_scores=masked_scores,
            validation=validation,
        )

    def decode(
        self,
        scored_productions: Mapping[str, Any] | Sequence[Any],
        *,
        family: str = "",
        source_text: str = "",
        context: Optional[Mapping[str, Any]] = None,
    ) -> ConstrainedLegalIRDecode:
        return self.mask_invalid_productions(
            scored_productions,
            family=family,
            source_text=source_text,
            context=context,
        )

    def frozen_tokenizer(self) -> "LegalIRFrozenTokenizer":
        """Return the decoder-bound frozen tokenizer without mutating vocabulary."""

        if self._frozen_tokenizer is None:
            self._frozen_tokenizer = LegalIRFrozenTokenizer.canonical()
        return self._frozen_tokenizer

    def encode_structured_output(
        self,
        candidate_ir: Any,
        *,
        family: str = "",
        source_text: str = "",
    ) -> "LegalIRTokenization":
        """Validate then freeze-encode a structured LegalIR payload."""

        validation = self.validate(
            candidate_ir,
            family=family,
            source_text=source_text,
        )
        return self.frozen_tokenizer().encode_canonical(
            candidate_ir,
            family=validation.family,
            source_text=source_text,
            accepted=validation.accepted,
        )

    def compatible_learned_architectures(
        self,
        *,
        seed: int = 0,
    ) -> dict[str, Any]:
        """Build both experiment arms on this decoder's frozen tokenizer."""

        return compatible_architecture_suite(
            seed=seed,
            tokenizer=self.frozen_tokenizer(),
        )

    def constraint_masks(
        self,
        prefix_ids: Sequence[int] = (),
        *,
        family: str = "",
        proof_state: Optional[Mapping[str, Any]] = None,
        config: Optional["LegalIRConstrainedDecodeConfig"] = None,
    ) -> "LegalIRConstraintMasks":
        """Return inspectable valid-token/grammar/binder/type/family masks."""

        return legal_ir_constraint_masks(
            prefix_ids,
            family=family,
            tokenizer=self.frozen_tokenizer(),
            proof_state=proof_state,
            config=config,
        )

    def decode_tokens(
        self,
        logits: Any = None,
        *,
        family: str = "",
        source_text: str = "",
        gold_token_ids: Optional[Sequence[int]] = None,
        gold_ir: Any = None,
        proof_state: Optional[Mapping[str, Any]] = None,
        architecture: Any = None,
        config: Optional["LegalIRConstrainedDecodeConfig"] = None,
    ) -> "LegalIRConstrainedTokenDecode":
        """Run bounded, mask-constrained token decoding."""

        return constrained_legal_ir_token_decode(
            logits,
            family=family,
            source_text=source_text,
            gold_token_ids=gold_token_ids,
            gold_ir=gold_ir,
            proof_state=proof_state,
            architecture=architecture,
            tokenizer=self.frozen_tokenizer(),
            config=config,
        )

    def admit_gold_path(
        self,
        gold_token_ids: Sequence[int] | None = None,
        *,
        gold_ir: Any = None,
        family: str = "",
        proof_state: Optional[Mapping[str, Any]] = None,
        config: Optional["LegalIRConstrainedDecodeConfig"] = None,
    ) -> "LegalIRGoldPathAdmission":
        """Admit a gold encoding only when every prefix stays legal."""

        return admit_legal_ir_gold_path(
            gold_token_ids,
            gold_ir=gold_ir,
            family=family,
            tokenizer=self.frozen_tokenizer(),
            proof_state=proof_state,
            config=config,
        )

    def gate_prover_call(
        self,
        candidate_ir: Any,
        *,
        family: str = "",
        source_text: str = "",
        gold_token_ids: Optional[Sequence[int]] = None,
        proof_state: Optional[Mapping[str, Any]] = None,
        config: Optional["LegalIRConstrainedDecodeConfig"] = None,
        prover: Optional[Callable[..., Any]] = None,
    ) -> "LegalIRProverAdmission":
        """Reject illegal candidates before they can spend proof budget."""

        return gate_legal_ir_prover_call(
            candidate_ir,
            family=family,
            source_text=source_text,
            gold_token_ids=gold_token_ids,
            tokenizer=self.frozen_tokenizer(),
            proof_state=proof_state,
            config=config,
            prover=prover,
        )


def canonical_legal_ir_grammar_family(family: str) -> str:
    """Normalize grammar families, including view-name aliases."""

    normalized = str(family or "").strip().lower().replace("-", "_").replace("/", ".")
    normalized = normalized.removeprefix("legal_ir_view.").removeprefix("legal-ir-view.")
    canonical = _FAMILY_ALIASES.get(normalized)
    if canonical:
        return canonical
    try:
        return canonical_legal_ir_evaluation_family(normalized)
    except ValueError:
        return "unscoped" if not normalized else normalized


def infer_legal_ir_grammar_family(candidate_ir: Any, *, family: str = "") -> str:
    explicit = canonical_legal_ir_grammar_family(family)
    if explicit and explicit != "unscoped":
        return explicit
    source = _object_to_mapping(candidate_ir)
    for key in ("family", "legal_ir_family", "view_family", "logic_family"):
        if key in source:
            resolved = canonical_legal_ir_grammar_family(str(source.get(key) or ""))
            if resolved != "unscoped":
                return resolved
    for key in ("legal_ir_view", "target_view", "view", "contract_id"):
        if key in source:
            resolved = canonical_legal_ir_grammar_family(str(source.get(key) or ""))
            if resolved != "unscoped":
                return resolved
    if any(key in source for key in ("obligations", "deontic_rules")):
        return "deontic"
    if any(key in source for key in ("triples", "frames", "frame_logic")):
        return "frame_logic"
    if any(key in source for key in ("formulas", "quantifiers", "predicates")):
        return "tdfol"
    if any(key in source for key in ("nodes", "edges", "graph")):
        return "knowledge_graphs"
    if any(key in source for key in ("counterexamples", "contexts", "events")):
        return "cec"
    if any(key in source for key in ("intervals", "temporal_windows", "relations")):
        return "temporal"
    if any(key in source for key in ("source_refs", "citations", "evidence")):
        return "provenance"
    if any(key in source for key in ("steps", "plan", "round_trip")):
        return "decompiler"
    return "unscoped"


def validate_legal_ir_candidate(
    candidate_ir: Any,
    *,
    family: str = "",
    source_text: str = "",
) -> LegalIRGrammarValidation:
    """Convenience API for validating one LegalIR payload."""

    return LegalIRGrammarDecoder().validate(
        candidate_ir,
        family=family,
        source_text=source_text,
    )


def constrained_legal_ir_decode(
    scored_productions: Mapping[str, Any] | Sequence[Any],
    *,
    family: str = "",
    source_text: str = "",
    context: Optional[Mapping[str, Any]] = None,
) -> ConstrainedLegalIRDecode:
    """Convenience API for masked production selection."""

    return LegalIRGrammarDecoder().decode(
        scored_productions,
        family=family,
        source_text=source_text,
        context=context,
    )


_MASKED_LOGIT: Final = -1.0e9
_CLOSED_PROOF_STATUSES: Final[frozenset[str]] = frozenset(
    {"proved", "disproved", "counterexample"}
)
_OPERATOR_VALUE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "modality",
        "operator",
        "slot",
        "label",
        "connective",
        "quantifier",
        "op",
        "operation",
        "predicate",
        "relation",
        "backend",
        "goal",
    }
)
_FAMILY_VALUE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "family",
        "legal_ir_family",
        "target_view",
        "view",
        "legal_ir_view",
        "contract_id",
    }
)
_BINDER_VALUE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "quantifier",
        "variables",
        "bind",
        "binder",
        "lambda",
        "let",
    }
)
_CROSS_FAMILY_HOSTS: Final[frozenset[str]] = frozenset(
    {
        "decompiler",
        "external_provers",
        "provenance",
    }
)
_SHARED_OPERATORS: Final[frozenset[str]] = frozenset(
    {"and", "or", "not", "implies", "iff"}
)
_FAMILY_OWNED_OPERATORS: Final[Mapping[str, frozenset[str]]] = {
    "deontic": frozenset(
        {
            "obligation",
            "permission",
            "prohibition",
            "duty",
            "right",
            "must",
            "may",
            "shall",
            "must_not",
        }
    ),
    "tdfol": frozenset({"and", "or", "not", "implies", "iff"}),
    "frame_logic": frozenset({"and", "or", "not", "implies"}),
    "temporal": frozenset({"and", "or", "not", "implies"}),
    "knowledge_graphs": frozenset({"and", "or", "not"}),
    "cec": frozenset({"and", "or", "not"}),
    "external_provers": frozenset({"and", "or", "not", "implies", "iff"}),
    "decompiler": frozenset(),
    "provenance": frozenset(),
}
_EXCLUSIVE_OPERATORS_BY_FAMILY: Final[Mapping[str, frozenset[str]]] = {
    "deontic": frozenset(
        {
            "obligation",
            "permission",
            "prohibition",
            "duty",
            "right",
            "must",
            "may",
            "shall",
            "must_not",
        }
    ),
}


class UnboundedLegalIRBeamError(ValueError):
    """Raised when a caller requests an unbounded or over-cap beam."""


class LegalIRConstraintBypassError(ValueError):
    """Raised when a caller tries to disable parser or type constraints."""


@dataclass(frozen=True, slots=True)
class LegalIRConstrainedDecodeConfig:
    """Hard-bounded constrained decoder contract. Parser/type cannot be bypassed."""

    beam_width: int = 4
    max_steps: int = 32
    max_expansions: int = 256
    fallback: str = "reject"
    proof_state_pruning: bool = False
    parser_pruning: bool = True
    type_checks: bool = True
    family: str = ""

    def __post_init__(self) -> None:
        width = int(self.beam_width)
        steps = int(self.max_steps)
        expansions = int(self.max_expansions)
        fallback = str(self.fallback or "reject").strip().lower()
        if width < 1 or width > LEGAL_IR_MAX_BEAM_WIDTH:
            raise UnboundedLegalIRBeamError(
                f"beam_width must be in 1..{LEGAL_IR_MAX_BEAM_WIDTH}, got {width}"
            )
        if steps < 1 or steps > LEGAL_IR_MAX_DECODE_STEPS:
            raise UnboundedLegalIRBeamError(
                f"max_steps must be in 1..{LEGAL_IR_MAX_DECODE_STEPS}, got {steps}"
            )
        if expansions < 1:
            raise UnboundedLegalIRBeamError("max_expansions must be a positive bound")
        if fallback not in LEGAL_IR_DECODE_FALLBACKS:
            raise ValueError(
                "fallback must be one of " + ", ".join(LEGAL_IR_DECODE_FALLBACKS)
            )
        if not bool(self.parser_pruning):
            raise LegalIRConstraintBypassError(
                "parser pruning cannot be disabled; parser/type bypass is prohibited"
            )
        if not bool(self.type_checks):
            raise LegalIRConstraintBypassError(
                "type checks cannot be disabled; parser/type bypass is prohibited"
            )
        object.__setattr__(self, "beam_width", width)
        object.__setattr__(self, "max_steps", steps)
        object.__setattr__(self, "max_expansions", expansions)
        object.__setattr__(self, "fallback", fallback)
        object.__setattr__(self, "family", str(self.family or ""))

    def bounds(self) -> dict[str, Any]:
        return {
            "beam_width": int(self.beam_width),
            "fallback": self.fallback,
            "max_beam_width": LEGAL_IR_MAX_BEAM_WIDTH,
            "max_expansions": int(self.max_expansions),
            "max_steps": int(self.max_steps),
            "parser_pruning": True,
            "proof_state_pruning": bool(self.proof_state_pruning),
            "type_checks": True,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.bounds()
        payload["family"] = self.family
        payload["schema"] = LEGAL_IR_CONSTRAINED_DECODER_SCHEMA
        return payload


@dataclass(frozen=True, slots=True)
class LegalIRConstraintMasks:
    """Separately inspectable constraint masks over the frozen vocabulary."""

    valid_token: tuple[bool, ...]
    grammar: tuple[bool, ...]
    binder: tuple[bool, ...]
    type: tuple[bool, ...]
    family: tuple[bool, ...]
    family_name: str = ""
    prefix_ids: tuple[int, ...] = ()
    schema: str = LEGAL_IR_CONSTRAINED_DECODER_SCHEMA

    def intersected(self) -> tuple[bool, ...]:
        return tuple(
            all(flags)
            for flags in zip(
                self.valid_token,
                self.grammar,
                self.binder,
                self.type,
                self.family,
                strict=True,
            )
        )

    def allowed_token_ids(self) -> tuple[int, ...]:
        return tuple(
            index for index, allowed in enumerate(self.intersected()) if allowed
        )

    def allowed_count(self) -> int:
        return sum(1 for allowed in self.intersected() if allowed)

    def layer(self, name: str) -> tuple[bool, ...]:
        layers = {
            "valid_token": self.valid_token,
            "grammar": self.grammar,
            "binder": self.binder,
            "type": self.type,
            "family": self.family,
        }
        if name not in layers:
            raise KeyError(f"unknown constraint mask {name!r}")
        return layers[name]

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed_count": self.allowed_count(),
            "allowed_token_ids": list(self.allowed_token_ids()),
            "family": self.family_name,
            "layers": {
                name: sum(1 for allowed in self.layer(name) if allowed)
                for name in LEGAL_IR_CONSTRAINT_MASK_NAMES
            },
            "prefix_ids": [int(token_id) for token_id in self.prefix_ids],
            "schema": self.schema,
            "vocabulary_size": len(self.valid_token),
        }


@dataclass(frozen=True, slots=True)
class LegalIRConstraintRejectionTelemetry:
    """Rejection telemetry for constrained decoding and prover admission."""

    contract: str = LEGAL_IR_CONSTRAINED_DECODER_INTERFACE
    schema: str = LEGAL_IR_CONSTRAINED_DECODER_SCHEMA
    family: str = ""
    rejection_reasons: tuple[str, ...] = ()
    masked_token_count: int = 0
    parser_pruned_count: int = 0
    proof_state_pruned_count: int = 0
    prover_calls: int = 0
    prover_calls_avoided: int = 0
    beam_width: int = 0
    max_beam_width: int = LEGAL_IR_MAX_BEAM_WIDTH
    fallback: str = "reject"
    fallback_used: str = ""
    bounds: Mapping[str, Any] = field(default_factory=dict)
    gold_path_preserved: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "beam_width": int(self.beam_width),
            "bounds": dict(self.bounds),
            "contract": self.contract,
            "family": self.family,
            "fallback": self.fallback,
            "fallback_used": self.fallback_used,
            "gold_path_preserved": bool(self.gold_path_preserved),
            "masked_token_count": int(self.masked_token_count),
            "max_beam_width": int(self.max_beam_width),
            "parser_pruned_count": int(self.parser_pruned_count),
            "proof_state_pruned_count": int(self.proof_state_pruned_count),
            "prover_calls": int(self.prover_calls),
            "prover_calls_avoided": int(self.prover_calls_avoided),
            "rejection_reasons": list(self.rejection_reasons),
            "schema": self.schema,
        }


@dataclass(frozen=True, slots=True)
class LegalIRBeamHypothesis:
    """One bounded beam hypothesis."""

    token_ids: tuple[int, ...]
    score: float
    finished: bool = False
    fallback_used: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "fallback_used": self.fallback_used,
            "finished": self.finished,
            "score": round(float(self.score), 12),
            "token_ids": [int(token_id) for token_id in self.token_ids],
        }


@dataclass(frozen=True, slots=True)
class LegalIRConstrainedTokenDecode:
    """Result of bounded grammar/binder/type/family/proof-state decoding."""

    accepted: bool
    family: str
    token_ids: tuple[int, ...]
    tokens: tuple[str, ...] = ()
    score: float = 0.0
    beam_width: int = 0
    steps: int = 0
    expansions: int = 0
    fallback: str = "reject"
    fallback_used: str = ""
    gold_path_preserved: bool = False
    parser_pruned: int = 0
    proof_state_pruned: int = 0
    hypotheses: tuple[LegalIRBeamHypothesis, ...] = ()
    telemetry: LegalIRConstraintRejectionTelemetry = field(
        default_factory=LegalIRConstraintRejectionTelemetry
    )
    schema: str = LEGAL_IR_CONSTRAINED_DECODER_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "beam_width": int(self.beam_width),
            "expansions": int(self.expansions),
            "fallback": self.fallback,
            "fallback_used": self.fallback_used,
            "family": self.family,
            "gold_path_preserved": self.gold_path_preserved,
            "hypotheses": [item.to_dict() for item in self.hypotheses],
            "parser_pruned": int(self.parser_pruned),
            "proof_state_pruned": int(self.proof_state_pruned),
            "schema": self.schema,
            "score": round(float(self.score), 12),
            "steps": int(self.steps),
            "telemetry": self.telemetry.to_dict(),
            "token_ids": [int(token_id) for token_id in self.token_ids],
            "tokens": list(self.tokens),
        }


@dataclass(frozen=True, slots=True)
class LegalIRGoldPathAdmission:
    """Whether every gold prefix remains inside the constraint masks."""

    admitted: bool
    family: str
    token_ids: tuple[int, ...]
    illegal_index: int = -1
    illegal_token_id: int = -1
    rejection_reasons: tuple[str, ...] = ()
    schema: str = LEGAL_IR_CONSTRAINED_DECODER_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted": self.admitted,
            "family": self.family,
            "illegal_index": int(self.illegal_index),
            "illegal_token_id": int(self.illegal_token_id),
            "rejection_reasons": list(self.rejection_reasons),
            "schema": self.schema,
            "token_ids": [int(token_id) for token_id in self.token_ids],
        }


@dataclass(frozen=True, slots=True)
class LegalIRProverAdmission:
    """Fail-closed prover gate: illegal candidates never spend proof budget."""

    admitted: bool
    family: str
    prover_calls: int
    candidate_ir: Any
    rejection_reasons: tuple[str, ...] = ()
    proof_result: Any = None
    telemetry: LegalIRConstraintRejectionTelemetry = field(
        default_factory=LegalIRConstraintRejectionTelemetry
    )
    schema: str = LEGAL_IR_CONSTRAINED_DECODER_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted": self.admitted,
            "family": self.family,
            "prover_calls": int(self.prover_calls),
            "rejection_reasons": list(self.rejection_reasons),
            "schema": self.schema,
            "telemetry": self.telemetry.to_dict(),
        }


def legal_ir_constrained_decode_config(
    **kwargs: Any,
) -> LegalIRConstrainedDecodeConfig:
    return LegalIRConstrainedDecodeConfig(**kwargs)


def legal_ir_constraint_masks(
    prefix_ids: Sequence[int] = (),
    *,
    family: str = "",
    tokenizer: Optional["LegalIRFrozenTokenizer"] = None,
    proof_state: Optional[Mapping[str, Any]] = None,
    config: Optional[LegalIRConstrainedDecodeConfig] = None,
) -> LegalIRConstraintMasks:
    """Build valid-token, grammar, binder, type, and family masks for a prefix."""

    frozen = tokenizer or LegalIRFrozenTokenizer.canonical()
    settings = config or LegalIRConstrainedDecodeConfig(family=family)
    family_name = canonical_legal_ir_grammar_family(family or settings.family)
    prefix = tuple(int(token_id) for token_id in prefix_ids)
    vocab_size = frozen.vocabulary_size
    valid_token = [False] * vocab_size
    grammar = [False] * vocab_size
    binder = [False] * vocab_size
    type_mask = [False] * vocab_size
    family_mask = [False] * vocab_size
    phase = _parser_phase(prefix, frozen, family=family_name)
    last_piece, last_class = _prefix_tail(prefix, frozen)
    proof = _normalize_proof_state(proof_state)
    prune_tactics = bool(settings.proof_state_pruning) and _proof_state_closed(proof)
    forbidden = set(proof.get("forbidden_token_ids") or ())
    forbidden.update(
        _token_id_for_piece(frozen, piece)
        for piece in proof.get("forbidden_tokens") or ()
        if _token_id_for_piece(frozen, piece) >= 0
    )

    for entry in frozen._entries:  # noqa: SLF001 - sealed vocab walk
        token_id = int(entry.token_id)
        piece = entry.piece
        token_class = entry.token_class
        if token_id in forbidden:
            continue
        if token_class == "padding" and phase != "complete":
            continue
        if token_class == "source_surface":
            continue
        valid_token[token_id] = True

        if token_class == "binder":
            if _binder_allowed(phase, family_name, last_piece, last_class):
                binder[token_id] = True
                grammar[token_id] = True
                type_mask[token_id] = True
                family_mask[token_id] = True
            continue
        binder[token_id] = True

        if token_class == "type":
            if _type_allowed(phase, family_name, piece):
                type_mask[token_id] = True
                grammar[token_id] = True
                family_mask[token_id] = True
            continue
        type_mask[token_id] = True

        if token_class == "family" or _alias_family_piece(family_name, piece, token_class):
            if _family_token_allowed(phase, family_name, piece, last_piece):
                family_mask[token_id] = True
                grammar[token_id] = True
            continue
        family_mask[token_id] = True

        if not _grammar_token_allowed(
            phase,
            family_name,
            piece,
            token_class,
            last_piece=last_piece,
            prune_tactics=prune_tactics,
            eos_id=frozen.eos_id,
            bos_id=frozen.bos_id,
            pad_id=frozen.pad_id,
        ):
            continue
        grammar[token_id] = True

    return LegalIRConstraintMasks(
        valid_token=tuple(valid_token),
        grammar=tuple(grammar),
        binder=tuple(binder),
        type=tuple(type_mask),
        family=tuple(family_mask),
        family_name=family_name,
        prefix_ids=prefix,
    )


def apply_legal_ir_constraint_masks(
    logits: Sequence[float],
    masks: LegalIRConstraintMasks,
) -> list[float]:
    """Intersect masks and zero out illegal logits without mutating inputs."""

    allowed = masks.intersected()
    if len(logits) != len(allowed):
        raise ValueError(
            f"logit width {len(logits)} does not match vocabulary {len(allowed)}"
        )
    return [
        float(logit) if flag else _MASKED_LOGIT
        for logit, flag in zip(logits, allowed, strict=True)
    ]


def admit_legal_ir_gold_path(
    gold_token_ids: Sequence[int] | None = None,
    *,
    gold_ir: Any = None,
    family: str = "",
    tokenizer: Optional["LegalIRFrozenTokenizer"] = None,
    proof_state: Optional[Mapping[str, Any]] = None,
    config: Optional[LegalIRConstrainedDecodeConfig] = None,
) -> LegalIRGoldPathAdmission:
    """Every gold prefix must remain a legal continuation."""

    frozen = tokenizer or LegalIRFrozenTokenizer.canonical()
    family_name = canonical_legal_ir_grammar_family(family)
    try:
        token_ids = _resolve_gold_token_ids(
            gold_token_ids,
            gold_ir=gold_ir,
            family=family_name,
            tokenizer=frozen,
        )
    except (UnknownFrozenTokenError, FrozenVocabularyMutationError, ValueError):
        return LegalIRGoldPathAdmission(
            admitted=False,
            family=family_name,
            token_ids=(),
            rejection_reasons=("gold_unencodable",),
        )
    for index, token_id in enumerate(token_ids):
        masks = legal_ir_constraint_masks(
            token_ids[:index],
            family=family_name,
            tokenizer=frozen,
            proof_state=proof_state,
            config=config,
        )
        if int(token_id) not in set(masks.allowed_token_ids()):
            reason = _gold_rejection_reason(frozen, int(token_id), index)
            return LegalIRGoldPathAdmission(
                admitted=False,
                family=family_name,
                token_ids=token_ids,
                illegal_index=index,
                illegal_token_id=int(token_id),
                rejection_reasons=(reason,),
            )
    return LegalIRGoldPathAdmission(
        admitted=bool(token_ids),
        family=family_name,
        token_ids=token_ids,
        rejection_reasons=() if token_ids else ("empty_gold_path",),
    )


def constrained_legal_ir_token_decode(
    logits: Any = None,
    *,
    family: str = "",
    source_text: str = "",
    gold_token_ids: Optional[Sequence[int]] = None,
    gold_ir: Any = None,
    proof_state: Optional[Mapping[str, Any]] = None,
    architecture: Any = None,
    tokenizer: Optional["LegalIRFrozenTokenizer"] = None,
    config: Optional[LegalIRConstrainedDecodeConfig] = None,
) -> LegalIRConstrainedTokenDecode:
    """Bounded beam search under grammar/binder/type/family/proof-state masks."""

    del source_text  # source surface stays off the canonical decode path
    frozen = tokenizer or LegalIRFrozenTokenizer.canonical()
    settings = config or LegalIRConstrainedDecodeConfig(family=family)
    family_name = canonical_legal_ir_grammar_family(family or settings.family)
    gold_ids = _resolve_gold_token_ids(
        gold_token_ids,
        gold_ir=gold_ir,
        family=family_name,
        tokenizer=frozen,
    )
    gold_admission = (
        admit_legal_ir_gold_path(
            gold_ids,
            family=family_name,
            tokenizer=frozen,
            proof_state=proof_state,
            config=settings,
        )
        if gold_ids
        else None
    )
    beams: list[LegalIRBeamHypothesis] = [
        LegalIRBeamHypothesis(token_ids=(), score=0.0, finished=False)
    ]
    parser_pruned = 0
    proof_pruned = 0
    expansions = 0
    steps = 0
    finished: list[LegalIRBeamHypothesis] = []

    for step in range(settings.max_steps):
        steps = step + 1
        live = [beam for beam in beams if not beam.finished]
        if not live:
            break
        next_beams: list[LegalIRBeamHypothesis] = []
        for beam in live:
            masks = legal_ir_constraint_masks(
                beam.token_ids,
                family=family_name,
                tokenizer=frozen,
                proof_state=proof_state,
                config=settings,
            )
            raw_logits = _logits_for_prefix(
                logits,
                prefix_ids=beam.token_ids,
                step=step,
                architecture=architecture,
                tokenizer=frozen,
            )
            masked = apply_legal_ir_constraint_masks(raw_logits, masks)
            ranked = _rank_allowed_tokens(masked, limit=settings.beam_width)
            if not ranked:
                parser_pruned += 1
                continue
            for token_id, token_score in ranked:
                if expansions >= settings.max_expansions and finished:
                    break
                expansions += 1
                entry = frozen.entry_for_id(token_id)
                if (
                    settings.proof_state_pruning
                    and entry.token_class == "tactic"
                    and _proof_state_closed(_normalize_proof_state(proof_state))
                ):
                    proof_pruned += 1
                    continue
                extended = (*beam.token_ids, int(token_id))
                done = int(token_id) == frozen.eos_id
                hypothesis = LegalIRBeamHypothesis(
                    token_ids=extended,
                    score=float(beam.score) + float(token_score),
                    finished=done,
                )
                if done:
                    finished.append(hypothesis)
                else:
                    next_beams.append(hypothesis)
            if expansions >= settings.max_expansions and finished:
                break
        next_beams.sort(key=lambda item: (-item.score, item.token_ids))
        beams = next_beams[: settings.beam_width]
        if expansions >= settings.max_expansions and finished:
            break

    selected, fallback_used, reasons = _select_decode_result(
        finished=finished,
        live=beams,
        settings=settings,
        gold_ids=gold_ids,
        gold_admission=gold_admission,
        tokenizer=frozen,
    )
    tokens = (
        tuple(frozen.decode_ids(selected.token_ids)) if selected.token_ids else ()
    )
    gold_preserved = bool(
        gold_admission
        and gold_admission.admitted
        and tuple(selected.token_ids) == gold_ids
    )
    accepted = bool(selected.finished and selected.token_ids and not reasons)
    telemetry = LegalIRConstraintRejectionTelemetry(
        family=family_name,
        rejection_reasons=reasons,
        masked_token_count=max(0, frozen.vocabulary_size - settings.beam_width),
        parser_pruned_count=parser_pruned,
        proof_state_pruned_count=proof_pruned,
        prover_calls=0,
        prover_calls_avoided=0 if accepted else 1,
        beam_width=settings.beam_width,
        fallback=settings.fallback,
        fallback_used=fallback_used,
        bounds=settings.bounds(),
        gold_path_preserved=gold_preserved,
    )
    return LegalIRConstrainedTokenDecode(
        accepted=accepted,
        family=family_name,
        token_ids=selected.token_ids,
        tokens=tokens,
        score=selected.score,
        beam_width=settings.beam_width,
        steps=steps,
        expansions=expansions,
        fallback=settings.fallback,
        fallback_used=fallback_used,
        gold_path_preserved=gold_preserved,
        parser_pruned=parser_pruned,
        proof_state_pruned=proof_pruned,
        hypotheses=tuple((finished or beams)[: settings.beam_width]),
        telemetry=telemetry,
    )


def gate_legal_ir_prover_call(
    candidate_ir: Any,
    *,
    family: str = "",
    source_text: str = "",
    gold_token_ids: Optional[Sequence[int]] = None,
    tokenizer: Optional["LegalIRFrozenTokenizer"] = None,
    proof_state: Optional[Mapping[str, Any]] = None,
    config: Optional[LegalIRConstrainedDecodeConfig] = None,
    prover: Optional[Callable[..., Any]] = None,
) -> LegalIRProverAdmission:
    """Call the prover only after grammar, token, and optional gold checks pass."""

    frozen = tokenizer or LegalIRFrozenTokenizer.canonical()
    settings = config or LegalIRConstrainedDecodeConfig(family=family)
    validation = validate_legal_ir_candidate(
        candidate_ir,
        family=family,
        source_text=source_text,
    )
    reasons = list(validation.rejection_reason_names)
    family_name = validation.family or canonical_legal_ir_grammar_family(family)
    if gold_token_ids is not None or _looks_like_token_ids(candidate_ir):
        token_ids = (
            tuple(int(token_id) for token_id in gold_token_ids)
            if gold_token_ids is not None
            else tuple(int(token_id) for token_id in candidate_ir)
        )
        admission = admit_legal_ir_gold_path(
            token_ids,
            family=family_name,
            tokenizer=frozen,
            proof_state=proof_state,
            config=settings,
        )
        if not admission.admitted:
            reasons.extend(admission.rejection_reasons or ("illegal_token_path",))
    admitted = not reasons
    proof_result = None
    prover_calls = 0
    if admitted and prover is not None:
        proof_result = prover(candidate_ir)
        prover_calls = 1
    telemetry = LegalIRConstraintRejectionTelemetry(
        family=family_name,
        rejection_reasons=tuple(dict.fromkeys(reasons)),
        prover_calls=prover_calls,
        prover_calls_avoided=0 if admitted else 1,
        beam_width=settings.beam_width,
        fallback=settings.fallback,
        fallback_used="" if admitted else "reject",
        bounds=settings.bounds(),
        gold_path_preserved=admitted,
    )
    return LegalIRProverAdmission(
        admitted=admitted,
        family=family_name,
        prover_calls=prover_calls,
        candidate_ir=candidate_ir,
        rejection_reasons=tuple(dict.fromkeys(reasons)),
        proof_result=proof_result,
        telemetry=telemetry,
    )


def compare_constrained_vs_unconstrained_proof_calls(
    candidates: Sequence[Any],
    *,
    family: str = "",
    source_text: str = "",
    proof_state: Optional[Mapping[str, Any]] = None,
    tokenizer: Optional["LegalIRFrozenTokenizer"] = None,
    config: Optional[LegalIRConstrainedDecodeConfig] = None,
    prover: Optional[Callable[..., Any]] = None,
) -> dict[str, Any]:
    """Compare prover spend with and without the constrained admission gate."""

    unconstrained_calls = 0
    constrained_calls = 0
    avoided = 0
    admissions: list[dict[str, Any]] = []
    active_prover = prover or (lambda payload: {"accepted": True, "payload": payload})
    for candidate in candidates:
        unconstrained_calls += 1
        admission = gate_legal_ir_prover_call(
            candidate,
            family=family,
            source_text=source_text,
            tokenizer=tokenizer,
            proof_state=proof_state,
            config=config,
            prover=active_prover,
        )
        constrained_calls += admission.prover_calls
        avoided += admission.telemetry.prover_calls_avoided
        admissions.append(admission.to_dict())
    return {
        "constrained_prover_calls": constrained_calls,
        "contract": LEGAL_IR_CONSTRAINED_DECODER_INTERFACE,
        "schema": LEGAL_IR_CONSTRAINED_DECODER_SCHEMA,
        "unconstrained_prover_calls": unconstrained_calls,
        "prover_calls_avoided": avoided,
        "saved_proof_budget": max(0, unconstrained_calls - constrained_calls),
        "admissions": admissions,
    }


def _parser_phase(
    prefix_ids: Sequence[int],
    tokenizer: "LegalIRFrozenTokenizer",
    *,
    family: str = "",
) -> str:
    if not prefix_ids:
        return "expect_bos"
    pieces = []
    classes = []
    for token_id in prefix_ids:
        entry = tokenizer.entry_for_id(int(token_id))
        pieces.append(entry.piece)
        classes.append(entry.token_class)
    if pieces[0] != "<bos>":
        return "invalid"
    if any(piece == "<eos>" for piece in pieces):
        return "complete"
    if len(pieces) == 1:
        return "expect_family"
    if classes[1] != "family" and pieces[1] != family:
        return "invalid"
    if len(pieces) == 2:
        return "expect_type"
    if classes[2] != "type":
        return "invalid"
    return "body"


def _alias_family_piece(family: str, piece: str, token_class: str) -> bool:
    return token_class == "identifier" and bool(family) and piece == family


def _prefix_tail(
    prefix_ids: Sequence[int],
    tokenizer: "LegalIRFrozenTokenizer",
) -> tuple[str, str]:
    if not prefix_ids:
        return "", ""
    entry = tokenizer.entry_for_id(int(prefix_ids[-1]))
    return entry.piece, entry.token_class


def _binder_allowed(phase: str, family: str, last_piece: str, last_class: str) -> bool:
    if phase != "body":
        return False
    if last_piece in _BINDER_VALUE_FIELDS or last_class == "binder":
        return True
    return family in {"tdfol", "decompiler"}


def _type_allowed(phase: str, family: str, piece: str) -> bool:
    if phase != "expect_type":
        return False
    expected = _family_output_type(family)
    return bool(expected) and piece == expected


def _family_token_allowed(phase: str, family: str, piece: str, last_piece: str) -> bool:
    if phase == "expect_family":
        return (not family or family == "unscoped") or piece == family
    if phase == "body" and last_piece in _FAMILY_VALUE_FIELDS:
        if last_piece == "target_view":
            return True
        return (not family or family == "unscoped") or piece == family
    return False


def _grammar_token_allowed(
    phase: str,
    family: str,
    piece: str,
    token_class: str,
    *,
    last_piece: str,
    prune_tactics: bool,
    eos_id: int,
    bos_id: int,
    pad_id: int,
) -> bool:
    del eos_id, bos_id, pad_id
    if phase == "expect_bos":
        return piece == "<bos>"
    if phase == "complete":
        return token_class == "padding"
    if phase in {"expect_family", "expect_type", "invalid"}:
        return False
    if piece == "<bos>":
        return False
    if piece == "<eos>":
        return True
    if token_class == "special":
        return False
    if token_class == "padding":
        return False
    if token_class == "tactic" and prune_tactics:
        return False
    if token_class == "operator":
        return _operator_allowed(family, piece, last_piece)
    if token_class == "production":
        spec_family = next(
            (
                spec.family
                for spec in default_legal_ir_production_specs()
                if spec.name == piece
            ),
            "",
        )
        return (not family or family == "unscoped" or spec_family == family) or (
            family in _CROSS_FAMILY_HOSTS
        )
    return token_class in {
        "special",
        "identifier",
        "source",
        "proof",
        "tactic",
        "production",
    }


def _operator_allowed(family: str, piece: str, last_piece: str) -> bool:
    if family in _CROSS_FAMILY_HOSTS or last_piece in _OPERATOR_VALUE_FIELDS:
        return True
    if piece in _SHARED_OPERATORS:
        return True
    owned = _FAMILY_OWNED_OPERATORS.get(family, frozenset())
    if piece in owned:
        return True
    for owner, exclusive in _EXCLUSIVE_OPERATORS_BY_FAMILY.items():
        if piece in exclusive and owner != family:
            return False
    return False


def _normalize_proof_state(proof_state: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    if not isinstance(proof_state, Mapping):
        return {}
    return dict(proof_state)


def _proof_state_closed(proof_state: Mapping[str, Any]) -> bool:
    status = str(
        proof_state.get("status")
        or proof_state.get("state")
        or proof_state.get("proof_status")
        or ""
    ).strip().lower()
    open_goals = proof_state.get("open_goals", proof_state.get("open_goal_count", 1))
    try:
        remaining = int(open_goals)
    except (TypeError, ValueError):
        remaining = 1
    if status in _CLOSED_PROOF_STATUSES and remaining <= 0:
        return True
    return bool(proof_state.get("closed")) or bool(proof_state.get("goal_closed"))


def _token_id_for_piece(tokenizer: "LegalIRFrozenTokenizer", piece: str) -> int:
    entry = tokenizer.lookup(str(piece))
    return -1 if entry is None else int(entry.token_id)


def _resolve_gold_token_ids(
    gold_token_ids: Sequence[int] | None,
    *,
    gold_ir: Any,
    family: str,
    tokenizer: "LegalIRFrozenTokenizer",
) -> tuple[int, ...]:
    if gold_token_ids is not None:
        return tuple(int(token_id) for token_id in gold_token_ids)
    if gold_ir is None:
        return ()
    encoding = tokenizer.encode_canonical(gold_ir, family=family)
    return tuple(int(token_id) for token_id in encoding.token_ids)


def _looks_like_token_ids(value: Any) -> bool:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return False
    return bool(value) and all(isinstance(item, int) and not isinstance(item, bool) for item in value)


def _gold_rejection_reason(
    tokenizer: "LegalIRFrozenTokenizer",
    token_id: int,
    index: int,
) -> str:
    try:
        entry = tokenizer.entry_for_id(token_id)
    except UnknownFrozenTokenError:
        return f"gold_token_outside_freeze:{index}"
    return f"gold_prefix_illegal:{entry.token_class}:{entry.piece}"


def _logits_for_prefix(
    logits: Any,
    *,
    prefix_ids: Sequence[int],
    step: int,
    architecture: Any,
    tokenizer: "LegalIRFrozenTokenizer",
) -> list[float]:
    vocab = tokenizer.vocabulary_size
    if callable(logits):
        values = logits(tuple(prefix_ids), step)
        return _coerce_logits(values, vocab)
    if isinstance(logits, Sequence) and logits and isinstance(logits[0], Sequence):
        row = logits[min(step, len(logits) - 1)]
        return _coerce_logits(row, vocab)
    if isinstance(logits, Sequence) and logits and not isinstance(logits[0], Sequence):
        return _coerce_logits(logits, vocab)
    if architecture is not None and hasattr(architecture, "encode_ids"):
        hidden = architecture.encode_ids(prefix_ids or (tokenizer.bos_id,))
        weight = architecture.parameters["reconstruction_weight"]
        bias = architecture.parameters["reconstruction_bias"]
        return _vec_add(_mat_vec(weight, hidden), bias)
    return [0.0] * vocab


def _coerce_logits(values: Sequence[Any], vocab_size: int) -> list[float]:
    coerced = [_finite_float(value, default=_MASKED_LOGIT) for value in values]
    if len(coerced) < vocab_size:
        coerced.extend([_MASKED_LOGIT] * (vocab_size - len(coerced)))
    return coerced[:vocab_size]


def _rank_allowed_tokens(
    masked_logits: Sequence[float],
    *,
    limit: int,
) -> tuple[tuple[int, float], ...]:
    ranked = [
        (index, float(score))
        for index, score in enumerate(masked_logits)
        if float(score) > _MASKED_LOGIT / 2.0
    ]
    ranked.sort(key=lambda item: (-item[1], item[0]))
    return tuple(ranked[: max(0, int(limit))])


def _select_decode_result(
    *,
    finished: Sequence[LegalIRBeamHypothesis],
    live: Sequence[LegalIRBeamHypothesis],
    settings: LegalIRConstrainedDecodeConfig,
    gold_ids: Sequence[int],
    gold_admission: LegalIRGoldPathAdmission | None,
    tokenizer: "LegalIRFrozenTokenizer",
) -> tuple[LegalIRBeamHypothesis, str, tuple[str, ...]]:
    if finished:
        if gold_ids:
            matching = [item for item in finished if tuple(item.token_ids) == tuple(gold_ids)]
            if matching:
                selected = max(
                    matching,
                    key=lambda item: (item.score, -len(item.token_ids), item.token_ids),
                )
                return selected, "", ()
        selected = max(
            finished,
            key=lambda item: (item.score, -len(item.token_ids), item.token_ids),
        )
        return selected, "", ()
    if settings.fallback == "gold_if_admitted" and gold_admission and gold_admission.admitted:
        return (
            LegalIRBeamHypothesis(
                token_ids=tuple(gold_ids),
                score=0.0,
                finished=True,
                fallback_used="gold_if_admitted",
            ),
            "gold_if_admitted",
            (),
        )
    if settings.fallback == "eos":
        base = live[0].token_ids if live else (tokenizer.bos_id,)
        if tokenizer.eos_id in set(base):
            return (
                LegalIRBeamHypothesis(token_ids=tuple(base), score=0.0, finished=True),
                "eos",
                (),
            )
        masks = legal_ir_constraint_masks(
            base,
            family=settings.family,
            tokenizer=tokenizer,
            config=settings,
        )
        if tokenizer.eos_id in set(masks.allowed_token_ids()):
            return (
                LegalIRBeamHypothesis(
                    token_ids=(*base, tokenizer.eos_id),
                    score=live[0].score if live else 0.0,
                    finished=True,
                    fallback_used="eos",
                ),
                "eos",
                (),
            )
    empty = LegalIRBeamHypothesis(token_ids=(), score=0.0, finished=False)
    return empty, "reject", ("no_finished_hypothesis",)


def default_legal_ir_production_specs() -> tuple[LegalIRProductionSpec, ...]:
    return (
        LegalIRProductionSpec(
            name="emit_deontic_rule",
            family="deontic",
            output_type="DeonticRule",
            required_fields=("modality", "subject", "action"),
            optional_fields=("condition", "exception", "object", "provenance"),
            description="obligation, permission, or prohibition over an actor/action",
        ),
        LegalIRProductionSpec(
            name="emit_frame_logic_triples",
            family="frame_logic",
            output_type="FrameLogicTriples",
            required_fields=("subject", "relation", "object"),
            optional_fields=("frame", "qualifiers", "provenance"),
        ),
        LegalIRProductionSpec(
            name="emit_tdfol_formula",
            family="tdfol",
            output_type="TDFOLFormula",
            required_fields=("predicate", "arguments"),
            optional_fields=("quantifier", "variables", "connective"),
        ),
        LegalIRProductionSpec(
            name="emit_knowledge_graph",
            family="knowledge_graphs",
            output_type="KnowledgeGraph",
            required_fields=("nodes", "edges"),
            optional_fields=("labels", "properties"),
        ),
        LegalIRProductionSpec(
            name="emit_cec_counterexample",
            family="cec",
            output_type="CounterexampleContext",
            required_fields=("events", "counterexamples"),
            optional_fields=("constraints", "contexts"),
        ),
        LegalIRProductionSpec(
            name="emit_external_prover_plan",
            family="external_provers",
            output_type="ExternalProverPlan",
            required_fields=("backend", "obligations"),
            optional_fields=("theory", "timeout", "route"),
        ),
        LegalIRProductionSpec(
            name="emit_temporal_window",
            family="temporal",
            output_type="TemporalWindow",
            required_fields=("intervals", "relations"),
            optional_fields=("bounds", "calendar", "timezone"),
        ),
        LegalIRProductionSpec(
            name="emit_provenance_receipt",
            family="provenance",
            output_type="ProvenanceReceipt",
            required_fields=("source_refs", "evidence"),
            optional_fields=("citations", "span_hashes", "receipts"),
        ),
        LegalIRProductionSpec(
            name="emit_decompiler_plan",
            family="decompiler",
            output_type="DecompilerPlan",
            required_fields=("steps", "target_view"),
            optional_fields=("round_trip", "source_copy_policy", "surface_template"),
        ),
    )


def grammar_metrics_from_validation(
    validation: LegalIRGrammarValidation,
) -> dict[str, float]:
    return validation.metrics()


def grammar_rejection_reason_names(
    validation: LegalIRGrammarValidation | ConstrainedLegalIRDecode,
) -> tuple[str, ...]:
    if isinstance(validation, ConstrainedLegalIRDecode):
        validation = validation.validation
    return validation.rejection_reason_names


def _validation(
    candidate_ir: Any,
    family: str,
    rejections: Sequence[LegalIRGrammarRejection],
    production: str,
) -> LegalIRGrammarValidation:
    deduped = tuple(_dedupe_rejections(rejections))
    return LegalIRGrammarValidation(
        accepted=not deduped,
        family=family,
        candidate_ir=candidate_ir,
        rejection_reasons=deduped,
        selected_productions=(production,) if production and not deduped else (),
        masked_productions=(production,) if production and deduped else (),
    )


def _dedupe_rejections(
    rejections: Sequence[LegalIRGrammarRejection],
) -> tuple[LegalIRGrammarRejection, ...]:
    seen: set[tuple[str, str, str, str]] = set()
    deduped: list[LegalIRGrammarRejection] = []
    for rejection in rejections:
        key = (
            rejection.reason,
            rejection.path,
            rejection.family,
            rejection.production,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(rejection)
    return tuple(deduped)


def _family_rejection(
    reason: str,
    *,
    family: str,
    path: str = "$",
    production: str = "",
    detail: str = "",
) -> LegalIRGrammarRejection:
    return LegalIRGrammarRejection(
        reason=reason,
        path=path,
        family=family,
        production=production,
        detail=detail,
    )


def _validate_deontic(
    candidate: Any,
    family: str,
    production: str,
) -> tuple[LegalIRGrammarRejection, ...]:
    source = _object_to_mapping(candidate)
    rules = _items_from(source, "obligations", "deontic_rules", "rules", "clauses")
    if not rules:
        return (_family_rejection("missing_deontic_rule", family=family, production=production),)
    rejections: list[LegalIRGrammarRejection] = []
    allowed_modalities = {"obligation", "permission", "prohibition", "duty", "right"}
    for index, rule in enumerate(rules):
        entry = _object_to_mapping(rule)
        modality = str(entry.get("modality") or entry.get("operator") or "").lower()
        if modality not in allowed_modalities:
            rejections.append(
                _family_rejection(
                    "invalid_deontic_modality",
                    family=family,
                    path=f"$.rules[{index}].modality",
                    production=production,
                    detail=modality,
                )
            )
        for key in ("subject", "action"):
            if not _nonempty_text(entry.get(key)):
                rejections.append(
                    _family_rejection(
                        f"missing_deontic_{key}",
                        family=family,
                        path=f"$.rules[{index}].{key}",
                        production=production,
                    )
                )
    return tuple(rejections)


def _validate_frame_logic(
    candidate: Any,
    family: str,
    production: str,
) -> tuple[LegalIRGrammarRejection, ...]:
    source = _object_to_mapping(candidate)
    triples = _items_from(source, "triples", "frame_logic", "relations")
    if not triples and isinstance(source.get("frames"), Sequence):
        triples = [
            relation
            for frame in _sequence(source.get("frames"))
            for relation in _items_from(_object_to_mapping(frame), "triples", "relations")
        ]
    if not triples:
        return (
            _family_rejection("missing_frame_logic_triple", family=family, production=production),
        )
    return tuple(
        rejection
        for index, triple in enumerate(triples)
        for rejection in _required_mapping_fields(
            triple,
            ("subject", "relation", "object"),
            family=family,
            path=f"$.triples[{index}]",
            production=production,
            reason_prefix="missing_frame_logic",
        )
    )


def _validate_tdfol(
    candidate: Any,
    family: str,
    production: str,
) -> tuple[LegalIRGrammarRejection, ...]:
    source = _object_to_mapping(candidate)
    formulas = _items_from(source, "formulas", "rules", "clauses")
    if not formulas and ("predicate" in source or "formula" in source):
        formulas = [source]
    if not formulas:
        return (_family_rejection("missing_tdfol_formula", family=family, production=production),)
    rejections: list[LegalIRGrammarRejection] = []
    for index, formula in enumerate(formulas):
        entry = _object_to_mapping(formula)
        predicate = str(entry.get("predicate") or entry.get("name") or "").strip()
        if not _IDENT_RE.match(predicate):
            rejections.append(
                _family_rejection(
                    "invalid_tdfol_predicate",
                    family=family,
                    path=f"$.formulas[{index}].predicate",
                    production=production,
                    detail=predicate,
                )
            )
        arguments = entry.get("arguments", entry.get("args"))
        if not _sequence(arguments):
            rejections.append(
                _family_rejection(
                    "missing_tdfol_arguments",
                    family=family,
                    path=f"$.formulas[{index}].arguments",
                    production=production,
                )
            )
        quantifier = str(entry.get("quantifier") or "").strip().lower()
        if quantifier and quantifier not in {"forall", "exists", "none"}:
            rejections.append(
                _family_rejection(
                    "invalid_tdfol_quantifier",
                    family=family,
                    path=f"$.formulas[{index}].quantifier",
                    production=production,
                    detail=quantifier,
                )
            )
    return tuple(rejections)


def _validate_kg(
    candidate: Any,
    family: str,
    production: str,
) -> tuple[LegalIRGrammarRejection, ...]:
    source = _object_to_mapping(candidate)
    graph = _object_to_mapping(source.get("graph")) if "graph" in source else source
    nodes = _sequence(graph.get("nodes"))
    edges = _sequence(graph.get("edges"))
    rejections: list[LegalIRGrammarRejection] = []
    if not nodes:
        rejections.append(
            _family_rejection("missing_kg_nodes", family=family, production=production)
        )
    if not edges:
        rejections.append(
            _family_rejection("missing_kg_edges", family=family, production=production)
        )
    node_ids = {
        str(_object_to_mapping(node).get("id") or "").strip()
        for node in nodes
        if str(_object_to_mapping(node).get("id") or "").strip()
    }
    for index, node in enumerate(nodes):
        rejections.extend(
            _required_mapping_fields(
                node,
                ("id", "label"),
                family=family,
                path=f"$.nodes[{index}]",
                production=production,
                reason_prefix="missing_kg_node",
            )
        )
    for index, edge in enumerate(edges):
        entry = _object_to_mapping(edge)
        rejections.extend(
            _required_mapping_fields(
                entry,
                ("source", "target", "label"),
                family=family,
                path=f"$.edges[{index}]",
                production=production,
                reason_prefix="missing_kg_edge",
            )
        )
        for endpoint in ("source", "target"):
            value = str(entry.get(endpoint) or "").strip()
            if value and node_ids and value not in node_ids:
                rejections.append(
                    _family_rejection(
                        "kg_edge_endpoint_unbound",
                        family=family,
                        path=f"$.edges[{index}].{endpoint}",
                        production=production,
                        detail=value,
                    )
                )
    return tuple(rejections)


def _validate_cec(
    candidate: Any,
    family: str,
    production: str,
) -> tuple[LegalIRGrammarRejection, ...]:
    source = _object_to_mapping(candidate)
    events = _items_from(source, "events", "event_trace")
    counterexamples = _items_from(source, "counterexamples", "counterexample")
    rejections: list[LegalIRGrammarRejection] = []
    if not events:
        rejections.append(
            _family_rejection("missing_cec_events", family=family, production=production)
        )
    if not counterexamples:
        rejections.append(
            _family_rejection("missing_cec_counterexample", family=family, production=production)
        )
    for index, event in enumerate(events):
        rejections.extend(
            _required_mapping_fields(
                event,
                ("id", "type"),
                family=family,
                path=f"$.events[{index}]",
                production=production,
                reason_prefix="missing_cec_event",
            )
        )
    return tuple(rejections)


def _validate_external_provers(
    candidate: Any,
    family: str,
    production: str,
) -> tuple[LegalIRGrammarRejection, ...]:
    source = _object_to_mapping(candidate)
    backend = str(source.get("backend") or source.get("prover") or "").strip()
    obligations = _items_from(source, "obligations", "proof_obligations", "goals")
    rejections: list[LegalIRGrammarRejection] = []
    if not backend:
        rejections.append(
            _family_rejection(
                "missing_external_prover_backend", family=family, production=production
            )
        )
    if not obligations:
        rejections.append(
            _family_rejection(
                "missing_external_prover_obligation", family=family, production=production
            )
        )
    return tuple(rejections)


def _validate_temporal(
    candidate: Any,
    family: str,
    production: str,
) -> tuple[LegalIRGrammarRejection, ...]:
    source = _object_to_mapping(candidate)
    intervals = _items_from(source, "intervals", "temporal_windows", "windows")
    relations = _items_from(source, "relations", "temporal_relations")
    rejections: list[LegalIRGrammarRejection] = []
    if not intervals:
        rejections.append(
            _family_rejection("missing_temporal_interval", family=family, production=production)
        )
    if not relations:
        rejections.append(
            _family_rejection("missing_temporal_relation", family=family, production=production)
        )
    for index, interval in enumerate(intervals):
        entry = _object_to_mapping(interval)
        if not any(
            _nonempty_text(entry.get(key))
            for key in ("start", "end", "duration", "date", "deadline")
        ):
            rejections.append(
                _family_rejection(
                    "missing_temporal_bound",
                    family=family,
                    path=f"$.intervals[{index}]",
                    production=production,
                )
            )
    return tuple(rejections)


def _validate_provenance(
    candidate: Any,
    family: str,
    production: str,
) -> tuple[LegalIRGrammarRejection, ...]:
    source = _object_to_mapping(candidate)
    refs = _items_from(source, "source_refs", "citations", "references")
    evidence = _items_from(source, "evidence", "receipts", "proof_evidence")
    rejections: list[LegalIRGrammarRejection] = []
    if not refs:
        rejections.append(
            _family_rejection("missing_provenance_source_ref", family=family, production=production)
        )
    if not evidence:
        rejections.append(
            _family_rejection("missing_provenance_evidence", family=family, production=production)
        )
    for index, ref in enumerate(refs):
        entry = _object_to_mapping(ref)
        if not any(
            _nonempty_text(entry.get(key))
            for key in ("citation", "document_id", "span_hash", "source_hash")
        ):
            rejections.append(
                _family_rejection(
                    "missing_provenance_reference_identifier",
                    family=family,
                    path=f"$.source_refs[{index}]",
                    production=production,
                )
            )
    return tuple(rejections)


def _validate_decompiler(
    candidate: Any,
    family: str,
    production: str,
) -> tuple[LegalIRGrammarRejection, ...]:
    source = _object_to_mapping(candidate)
    plan = (
        _object_to_mapping(source.get("plan"))
        if isinstance(source.get("plan"), Mapping)
        else source
    )
    steps = _items_from(plan, "steps", "operations")
    target_view = str(plan.get("target_view") or plan.get("legal_ir_view") or "").strip()
    rejections: list[LegalIRGrammarRejection] = []
    if not steps:
        rejections.append(
            _family_rejection("missing_decompiler_steps", family=family, production=production)
        )
    if not target_view:
        rejections.append(
            _family_rejection(
                "missing_decompiler_target_view", family=family, production=production
            )
        )
    policy = str(plan.get("source_copy_policy") or "").strip().lower()
    if policy and policy not in {"hash_only", "span_hash_only", "citation_only", "no_source_text"}:
        rejections.append(
            _family_rejection(
                "unsafe_decompiler_source_copy_policy",
                family=family,
                path="$.source_copy_policy",
                production=production,
                detail=policy,
            )
        )
    for index, step in enumerate(steps):
        entry = _object_to_mapping(step)
        if not _nonempty_text(entry.get("op", entry.get("operation"))):
            rejections.append(
                _family_rejection(
                    "missing_decompiler_step_operation",
                    family=family,
                    path=f"$.steps[{index}].op",
                    production=production,
                )
            )
    return tuple(rejections)


_FAMILY_VALIDATORS = {
    "deontic": _validate_deontic,
    "frame_logic": _validate_frame_logic,
    "tdfol": _validate_tdfol,
    "knowledge_graphs": _validate_kg,
    "cec": _validate_cec,
    "external_provers": _validate_external_provers,
    "temporal": _validate_temporal,
    "provenance": _validate_provenance,
    "decompiler": _validate_decompiler,
}


def _required_mapping_fields(
    value: Any,
    fields: Sequence[str],
    *,
    family: str,
    path: str,
    production: str,
    reason_prefix: str,
) -> tuple[LegalIRGrammarRejection, ...]:
    source = _object_to_mapping(value)
    return tuple(
        _family_rejection(
            f"{reason_prefix}_{field}",
            family=family,
            path=f"{path}.{field}",
            production=production,
        )
        for field in fields
        if not _nonempty_text(source.get(field))
    )


def _source_copy_rejections(
    candidate: Any,
    *,
    source_text: str,
    family: str,
    production: str,
) -> tuple[LegalIRGrammarRejection, ...]:
    source_norm = _normalize_text(source_text)
    rejections: list[LegalIRGrammarRejection] = []

    def visit(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                key_text = str(key)
                child_path = f"{path}.{key_text}" if path else key_text
                if _SOURCE_TEXT_FIELD_RE.search(key_text):
                    rejections.append(
                        _family_rejection(
                            "raw_source_copy_field",
                            family=family,
                            path=child_path,
                            production=production,
                            detail=key_text,
                        )
                    )
                visit(child, child_path)
            return
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")
            return
        if not isinstance(value, str):
            return
        text = value.strip()
        if not text:
            return
        if _PLACEHOLDER_RE.search(text):
            rejections.append(
                _family_rejection(
                    "source_copy_placeholder",
                    family=family,
                    path=path or "$",
                    production=production,
                    detail=text[:80],
                )
            )
            return
        if source_norm and len(_normalize_text(text)) >= 48:
            text_norm = _normalize_text(text)
            if text_norm == source_norm or text_norm in source_norm:
                rejections.append(
                    _family_rejection(
                        "source_copy_placeholder",
                        family=family,
                        path=path or "$",
                        production=production,
                        detail="candidate copies source text",
                    )
                )

    visit(candidate, "$")
    return tuple(rejections)


def _production_rows(
    scored_productions: Mapping[str, Any] | Sequence[Any],
    *,
    context: Optional[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    payloads = {}
    if isinstance(context, Mapping):
        raw_payloads = context.get("productions") or context.get("outputs") or {}
        if isinstance(raw_payloads, Mapping):
            payloads = dict(raw_payloads)
    rows: list[dict[str, Any]] = []
    if isinstance(scored_productions, Mapping):
        for name, value in scored_productions.items():
            row = _row_from_value(str(name), value, payloads.get(name))
            rows.append(row)
    else:
        for index, value in enumerate(_sequence(scored_productions)):
            rows.append(_row_from_value(f"production_{index}", value, None))
    return tuple(rows)


def _row_from_value(name: str, value: Any, context_output: Any) -> dict[str, Any]:
    source = _object_to_mapping(value)
    if source:
        row_name = str(source.get("name") or source.get("production") or name)
        score = _finite_float(source.get("score", source.get("logit", 0.0)))
        output = (
            source.get("output")
            if "output" in source
            else source.get("candidate_ir")
            if "candidate_ir" in source
            else source.get("decoded_ir")
            if "decoded_ir" in source
            else context_output
        )
        return {
            "family": source.get("family") or source.get("legal_ir_family") or "",
            "name": row_name,
            "output": output,
            "score": score,
        }
    return {
        "family": "",
        "name": name,
        "output": context_output,
        "score": _finite_float(value),
    }


def _mapping_or_sequence(value: Any) -> Any:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    source = _object_to_mapping(value)
    return source or None


def _object_to_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if value is None or isinstance(value, (str, bytes, bytearray, int, float, bool)):
        return {}
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            mapped = to_dict()
        except TypeError:
            mapped = None
        if isinstance(mapped, Mapping):
            return dict(mapped)
    slots = getattr(value, "__slots__", ())
    if isinstance(slots, str):
        slots = (slots,)
    names = set(getattr(value, "__dict__", {}) or {})
    names.update(str(name) for name in slots if str(name) != "__weakref__")
    return {
        name: getattr(value, name)
        for name in sorted(names)
        if hasattr(value, name) and not name.startswith("_")
    }


def _items_from(source: Mapping[str, Any], *keys: str) -> tuple[Any, ...]:
    for key in keys:
        if key not in source:
            continue
        value = source.get(key)
        if isinstance(value, Mapping):
            return (value,)
        items = _sequence(value)
        if items:
            return items
    return ()


def _sequence(value: Any) -> tuple[Any, ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(value)
    if value is None:
        return ()
    return ()


def _nonempty_text(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip()) and not _PLACEHOLDER_RE.search(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return math.isfinite(float(value))
    return value is not None


def _finite_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _metric_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_") or "unknown"


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _stable_digest(value: Any) -> str:
    return hashlib.sha256(repr(value).encode("utf-8", "replace")).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _content_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _content_cid(value: Any) -> str:
    return f"sha256:{_content_sha256(value)}"


class FrozenVocabularyMutationError(ValueError):
    """Raised when a caller attempts to mutate a frozen tokenizer vocabulary."""


class UnknownFrozenTokenError(ValueError):
    """Raised when a closed-class token is absent from the frozen vocabulary."""


@dataclass(frozen=True, slots=True)
class LegalIRVocabEntry:
    """One frozen vocabulary row with an immutable token class."""

    token_id: int
    piece: str
    token_class: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "piece": self.piece,
            "token_class": self.token_class,
            "token_id": int(self.token_id),
        }


@dataclass(frozen=True, slots=True)
class LegalIRToken:
    """One encoded token, including class and surface/canonical origin."""

    token_id: int
    piece: str
    token_class: str
    surface: str = "canonical"
    source_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "piece": self.piece,
            "source_hash": self.source_hash,
            "surface": self.surface,
            "token_class": self.token_class,
            "token_id": int(self.token_id),
        }


@dataclass(frozen=True, slots=True)
class LegalIRTokenization:
    """Deterministic encoding of one structured or source-surface payload."""

    token_ids: tuple[int, ...]
    tokens: tuple[LegalIRToken, ...]
    token_class_counts: Mapping[str, int]
    vocabulary_cid: str
    vocabulary_sha256: str
    source_surface_separated: bool
    source_surface_token_count: int
    canonical_token_count: int
    accepted: bool = True
    family: str = ""
    schema_version: str = LEGAL_IR_FROZEN_TOKENIZER_SCHEMA_VERSION

    def token_class_histogram(self) -> dict[str, int]:
        return {
            name: int(self.token_class_counts.get(name, 0)) for name in LEGAL_IR_TOKEN_CLASSES
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "canonical_token_count": int(self.canonical_token_count),
            "family": self.family,
            "schema_version": self.schema_version,
            "source_surface_separated": self.source_surface_separated,
            "source_surface_token_count": int(self.source_surface_token_count),
            "token_class_counts": self.token_class_histogram(),
            "token_ids": [int(token_id) for token_id in self.token_ids],
            "tokens": [token.to_dict() for token in self.tokens],
            "vocabulary_cid": self.vocabulary_cid,
            "vocabulary_sha256": self.vocabulary_sha256,
        }


class LegalIRFrozenTokenizer:
    """Canonical, fail-closed tokenizer with a frozen structured vocabulary.

    Source-surface text is encoded on a separate path and never mutates the
    canonical vocabulary.  Closed-class unknowns fail closed.  Open identifiers
    hash into a fixed bucket table that is part of the freeze.
    """

    def __init__(
        self,
        *,
        entries: Optional[Sequence[LegalIRVocabEntry]] = None,
        frozen: bool = True,
    ) -> None:
        using_canonical_default = entries is None
        resolved = tuple(entries or default_legal_ir_frozen_vocabulary())
        self._entries = resolved
        self._piece_to_entry = {entry.piece: entry for entry in resolved}
        self._id_to_entry = {entry.token_id: entry for entry in resolved}
        if len(self._piece_to_entry) != len(resolved):
            raise ValueError("frozen vocabulary pieces must be unique")
        if list(entry.token_id for entry in resolved) != list(range(len(resolved))):
            raise ValueError("frozen vocabulary token ids must be contiguous from 0")
        self._frozen = bool(frozen)
        vocabulary_payload = self.vocabulary_manifest()
        self._vocabulary_sha256 = _content_sha256(vocabulary_payload)
        self._vocabulary_cid = _content_cid(vocabulary_payload)
        if using_canonical_default:
            if self._vocabulary_cid != LEGAL_IR_CANONICAL_VOCABULARY_CID:
                raise ValueError(
                    "canonical frozen vocabulary CID drifted from the sealed digest"
                )
            if len(resolved) != LEGAL_IR_CANONICAL_VOCABULARY_SIZE:
                raise ValueError(
                    "canonical frozen vocabulary size drifted from the sealed size"
                )

    @classmethod
    def canonical(cls) -> "LegalIRFrozenTokenizer":
        return cls()

    @property
    def frozen(self) -> bool:
        return self._frozen

    @property
    def vocabulary_size(self) -> int:
        return len(self._entries)

    @property
    def vocabulary_cid(self) -> str:
        return self._vocabulary_cid

    @property
    def vocabulary_sha256(self) -> str:
        return f"sha256:{self._vocabulary_sha256}"

    @property
    def pad_id(self) -> int:
        return self._piece_to_entry["<pad>"].token_id

    @property
    def bos_id(self) -> int:
        return self._piece_to_entry["<bos>"].token_id

    @property
    def eos_id(self) -> int:
        return self._piece_to_entry["<eos>"].token_id

    @property
    def unk_id(self) -> int:
        return self._piece_to_entry["<unk>"].token_id

    @property
    def source_ref_id(self) -> int:
        return self._piece_to_entry["<source_ref>"].token_id

    def freeze(self) -> "LegalIRFrozenTokenizer":
        if self._frozen:
            return self
        return LegalIRFrozenTokenizer(entries=self._entries, frozen=True)

    def lookup(self, piece: str) -> Optional[LegalIRVocabEntry]:
        return self._piece_to_entry.get(str(piece))

    def entry_for_id(self, token_id: int) -> LegalIRVocabEntry:
        try:
            return self._id_to_entry[int(token_id)]
        except KeyError as exc:
            raise UnknownFrozenTokenError(f"token id {token_id} is outside the freeze") from exc

    def require(self, piece: str, *, token_class: str = "") -> LegalIRVocabEntry:
        entry = self.lookup(piece)
        if entry is None:
            raise UnknownFrozenTokenError(
                f"closed-class token {piece!r} is absent from the frozen vocabulary"
            )
        if token_class and entry.token_class != token_class:
            raise UnknownFrozenTokenError(
                f"token {piece!r} has class {entry.token_class!r}, expected {token_class!r}"
            )
        return entry

    def add_token(self, piece: str, token_class: str) -> None:
        raise FrozenVocabularyMutationError(
            "frozen tokenizer vocabulary cannot be mutated; supersede with a new CID"
        )

    def encode_canonical(
        self,
        candidate_ir: Any,
        *,
        family: str = "",
        source_text: str = "",
        accepted: bool = True,
        max_length: int = 64,
    ) -> LegalIRTokenization:
        if not self._frozen:
            raise FrozenVocabularyMutationError("canonical encoding requires a frozen vocabulary")
        family_name = infer_legal_ir_grammar_family(candidate_ir, family=family)
        tokens: list[LegalIRToken] = [self._special_token("<bos>")]
        if family_name and family_name != "unscoped":
            tokens.append(self._closed_token(family_name, token_class="family"))
        type_piece = _family_output_type(family_name)
        if type_piece:
            tokens.append(self._closed_token(type_piece, token_class="type"))
        tokens.extend(self._walk_structured(candidate_ir, family=family_name))
        tokens.append(self._special_token("<eos>"))
        if len(tokens) > max_length:
            tokens = [*tokens[: max_length - 1], self._special_token("<eos>")]
        return self._finalize_tokenization(
            tokens,
            family=family_name,
            accepted=accepted,
            source_text=source_text,
        )

    def encode_source_surface(
        self,
        source_text: str,
        *,
        family: str = "",
        max_length: int = 32,
    ) -> LegalIRTokenization:
        """Encode raw source without touching the canonical vocabulary."""

        normalized = _normalize_text(source_text)
        tokens: list[LegalIRToken] = [self._special_token("<bos>")]
        tokens.append(self._special_token("<source_ref>"))
        if normalized:
            digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
            for index, chunk in enumerate(_chunks(digest, 8)[: max(0, max_length - 3)]):
                tokens.append(
                    LegalIRToken(
                        token_id=self.source_ref_id,
                        piece="<source_ref>",
                        token_class="source_surface",
                        surface="source",
                        source_hash=f"{index:02d}:{chunk}",
                    )
                )
        tokens.append(self._special_token("<eos>"))
        return self._finalize_tokenization(
            tokens,
            family=canonical_legal_ir_grammar_family(family),
            accepted=True,
            source_text=source_text,
            source_surface_only=True,
        )

    def encode_pair(
        self,
        candidate_ir: Any,
        *,
        family: str = "",
        source_text: str = "",
    ) -> dict[str, LegalIRTokenization]:
        """Return separately addressed canonical and source-surface encodings."""

        return {
            "canonical": self.encode_canonical(
                candidate_ir,
                family=family,
                source_text=source_text,
            ),
            "source_surface": self.encode_source_surface(
                source_text,
                family=family,
            ),
        }

    def pad_ids(self, token_ids: Sequence[int], *, max_length: int) -> list[int]:
        bounded = [int(token_id) for token_id in token_ids[: max(0, int(max_length))]]
        if len(bounded) < max_length:
            bounded.extend([self.pad_id] * (int(max_length) - len(bounded)))
        return bounded

    def decode_ids(self, token_ids: Sequence[int]) -> tuple[str, ...]:
        return tuple(self.entry_for_id(token_id).piece for token_id in token_ids)

    def token_class_for_id(self, token_id: int) -> str:
        return self.entry_for_id(token_id).token_class

    def vocabulary_manifest(self) -> dict[str, Any]:
        return {
            "identifier_bucket_count": LEGAL_IR_IDENTIFIER_BUCKET_COUNT,
            "interface": LEGAL_IR_FROZEN_TOKENIZER_INTERFACE,
            "mutation_policy": "supersede_never_overwrite",
            "schema": LEGAL_IR_FROZEN_VOCABULARY_SCHEMA,
            "schema_version": LEGAL_IR_FROZEN_TOKENIZER_SCHEMA_VERSION,
            "token_classes": list(LEGAL_IR_TOKEN_CLASSES),
            "tokens": [entry.to_dict() for entry in self._entries],
            "unknown_token_behavior": "fail_closed",
            "vocabulary_size": len(self._entries),
        }

    def to_dict(self) -> dict[str, Any]:
        manifest = self.vocabulary_manifest()
        manifest["frozen"] = self._frozen
        manifest["vocabulary_cid"] = self.vocabulary_cid
        manifest["vocabulary_sha256"] = self.vocabulary_sha256
        return manifest

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "LegalIRFrozenTokenizer":
        tokens = payload.get("tokens")
        if not isinstance(tokens, Sequence):
            raise ValueError("tokenizer payload is missing tokens")
        entries = []
        for index, row in enumerate(tokens):
            if not isinstance(row, Mapping):
                raise ValueError("tokenizer token row must be a mapping")
            entries.append(
                LegalIRVocabEntry(
                    token_id=int(row.get("token_id", index)),
                    piece=str(row.get("piece") or ""),
                    token_class=str(row.get("token_class") or ""),
                )
            )
        tokenizer = cls(entries=entries, frozen=bool(payload.get("frozen", True)))
        expected_cid = str(payload.get("vocabulary_cid") or "")
        if expected_cid and expected_cid != tokenizer.vocabulary_cid:
            raise ValueError("tokenizer vocabulary CID does not match payload")
        return tokenizer

    def _special_token(self, piece: str) -> LegalIRToken:
        entry = self.require(piece)
        return LegalIRToken(
            token_id=entry.token_id,
            piece=entry.piece,
            token_class=entry.token_class,
        )

    def _closed_token(self, piece: str, *, token_class: str) -> LegalIRToken:
        entry = self.require(piece, token_class=token_class)
        return LegalIRToken(
            token_id=entry.token_id,
            piece=entry.piece,
            token_class=entry.token_class,
        )

    def _identifier_or_source_token(self, value: str, *, field_name: str) -> LegalIRToken:
        text = str(value or "").strip()
        if not text:
            raise UnknownFrozenTokenError(f"empty identifier at {field_name}")
        if _SOURCE_TEXT_FIELD_RE.match(field_name) or _PLACEHOLDER_RE.search(text):
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            return LegalIRToken(
                token_id=self.source_ref_id,
                piece="<source_ref>",
                token_class="source",
                surface="source",
                source_hash=digest,
            )
        existing = self.lookup(text)
        if existing is not None:
            return LegalIRToken(
                token_id=existing.token_id,
                piece=existing.piece,
                token_class=existing.token_class,
            )
        if " " in text or len(text) > 32:
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            return LegalIRToken(
                token_id=self.source_ref_id,
                piece="<source_ref>",
                token_class="source",
                surface="source",
                source_hash=digest,
            )
        bucket = int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16) % (
            LEGAL_IR_IDENTIFIER_BUCKET_COUNT
        )
        piece = f"<id_bucket_{bucket:02d}>"
        entry = self.require(piece, token_class="identifier")
        return LegalIRToken(
            token_id=entry.token_id,
            piece=entry.piece,
            token_class=entry.token_class,
            source_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )

    def _walk_structured(
        self,
        value: Any,
        *,
        family: str,
        path: str = "$",
    ) -> list[LegalIRToken]:
        tokens: list[LegalIRToken] = []
        if isinstance(value, Mapping):
            for key in sorted(str(item) for item in value.keys()):
                field_entry = self.lookup(key)
                if field_entry is not None and field_entry.token_class in {
                    "identifier",
                    "operator",
                    "production",
                    "type",
                    "family",
                }:
                    tokens.append(
                        LegalIRToken(
                            token_id=field_entry.token_id,
                            piece=field_entry.piece,
                            token_class=field_entry.token_class,
                        )
                    )
                tokens.extend(
                    self._walk_structured(
                        value.get(key),
                        family=family,
                        path=f"{path}.{key}",
                    )
                )
            return tokens
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for index, item in enumerate(value):
                tokens.extend(
                    self._walk_structured(
                        item,
                        family=family,
                        path=f"{path}[{index}]",
                    )
                )
            return tokens
        if isinstance(value, bool) or value is None:
            return tokens
        if isinstance(value, (int, float)):
            return tokens
        text = str(value).strip()
        if not text:
            return tokens
        existing = self.lookup(text)
        if existing is not None:
            if existing.token_class in LEGAL_IR_CLOSED_TOKEN_CLASSES or existing.token_class in {
                "identifier",
                "source",
            }:
                tokens.append(
                    LegalIRToken(
                        token_id=existing.token_id,
                        piece=existing.piece,
                        token_class=existing.token_class,
                    )
                )
                return tokens
        field_name = path.rsplit(".", 1)[-1]
        if field_name in _CLOSED_VALUE_FIELDS and existing is None:
            raise UnknownFrozenTokenError(
                f"closed-class value {text!r} at {path} is absent from the freeze"
            )
        tokens.append(self._identifier_or_source_token(text, field_name=field_name))
        return tokens

    def _finalize_tokenization(
        self,
        tokens: Sequence[LegalIRToken],
        *,
        family: str,
        accepted: bool,
        source_text: str,
        source_surface_only: bool = False,
    ) -> LegalIRTokenization:
        counts = {name: 0 for name in LEGAL_IR_TOKEN_CLASSES}
        source_surface_count = 0
        canonical_count = 0
        for token in tokens:
            counts[token.token_class] = counts.get(token.token_class, 0) + 1
            if token.surface == "source" or token.token_class == "source_surface":
                if not source_surface_only:
                    raise UnknownFrozenTokenError(
                        "source-surface tokens are rejected on the canonical IR path"
                    )
                source_surface_count += 1
            else:
                canonical_count += 1
        return LegalIRTokenization(
            token_ids=tuple(token.token_id for token in tokens),
            tokens=tuple(tokens),
            token_class_counts=counts,
            vocabulary_cid=self.vocabulary_cid,
            vocabulary_sha256=self.vocabulary_sha256,
            source_surface_separated=True,
            source_surface_token_count=source_surface_count,
            canonical_token_count=canonical_count,
            accepted=accepted,
            family=family,
        )


def default_legal_ir_frozen_vocabulary() -> tuple[LegalIRVocabEntry, ...]:
    """Return the sealed canonical vocabulary used by both experiment arms."""

    pieces: list[tuple[str, str]] = [
        ("<pad>", "padding"),
        ("<bos>", "special"),
        ("<eos>", "special"),
        ("<sep>", "special"),
        ("<mask>", "special"),
        ("<unk>", "special"),
        ("<source_ref>", "source"),
        ("forall", "binder"),
        ("exists", "binder"),
        ("lambda", "binder"),
        ("let", "binder"),
        ("bind", "binder"),
        ("obligation", "operator"),
        ("permission", "operator"),
        ("prohibition", "operator"),
        ("duty", "operator"),
        ("right", "operator"),
        ("and", "operator"),
        ("or", "operator"),
        ("not", "operator"),
        ("implies", "operator"),
        ("iff", "operator"),
        ("must", "operator"),
        ("may", "operator"),
        ("shall", "operator"),
        ("must_not", "operator"),
        ("DeonticRule", "type"),
        ("FrameLogicTriples", "type"),
        ("TDFOLFormula", "type"),
        ("KnowledgeGraph", "type"),
        ("CounterexampleContext", "type"),
        ("ExternalProverPlan", "type"),
        ("TemporalWindow", "type"),
        ("ProvenanceReceipt", "type"),
        ("DecompilerPlan", "type"),
        ("proved", "proof"),
        ("disproved", "proof"),
        ("timeout", "proof"),
        ("unknown", "proof"),
        ("counterexample", "proof"),
        ("unchecked", "proof"),
        ("intro", "tactic"),
        ("apply", "tactic"),
        ("simp", "tactic"),
        ("cases", "tactic"),
        ("rewrite", "tactic"),
        ("hammer", "tactic"),
        ("modality", "identifier"),
        ("subject", "identifier"),
        ("action", "identifier"),
        ("condition", "identifier"),
        ("exception", "identifier"),
        ("object", "identifier"),
        ("provenance", "identifier"),
        ("relation", "identifier"),
        ("frame", "identifier"),
        ("qualifiers", "identifier"),
        ("predicate", "identifier"),
        ("arguments", "identifier"),
        ("quantifier", "identifier"),
        ("variables", "identifier"),
        ("connective", "identifier"),
        ("nodes", "identifier"),
        ("edges", "identifier"),
        ("labels", "identifier"),
        ("properties", "identifier"),
        ("events", "identifier"),
        ("counterexamples", "identifier"),
        ("constraints", "identifier"),
        ("contexts", "identifier"),
        ("backend", "identifier"),
        ("obligations", "identifier"),
        ("theory", "identifier"),
        ("timeout", "identifier"),
        ("route", "identifier"),
        ("intervals", "identifier"),
        ("relations", "identifier"),
        ("bounds", "identifier"),
        ("calendar", "identifier"),
        ("timezone", "identifier"),
        ("source_refs", "identifier"),
        ("evidence", "identifier"),
        ("citations", "identifier"),
        ("span_hashes", "identifier"),
        ("receipts", "identifier"),
        ("steps", "identifier"),
        ("target_view", "identifier"),
        ("round_trip", "identifier"),
        ("source_copy_policy", "identifier"),
        ("surface_template", "identifier"),
        ("family", "identifier"),
        ("rules", "identifier"),
        ("triples", "identifier"),
        ("formulas", "identifier"),
        ("hash_only", "identifier"),
    ]
    for family in LEGAL_IR_GRAMMAR_FAMILIES:
        pieces.append((family, "family"))
    for spec in default_legal_ir_production_specs():
        pieces.append((spec.name, "production"))
    for index in range(LEGAL_IR_IDENTIFIER_BUCKET_COUNT):
        pieces.append((f"<id_bucket_{index:02d}>", "identifier"))

    seen: set[str] = set()
    entries: list[LegalIRVocabEntry] = []
    for piece, token_class in pieces:
        if piece in seen:
            continue
        if token_class not in LEGAL_IR_TOKEN_CLASSES:
            raise ValueError(f"unknown token class {token_class!r}")
        seen.add(piece)
        entries.append(
            LegalIRVocabEntry(
                token_id=len(entries),
                piece=piece,
                token_class=token_class,
            )
        )
    return tuple(entries)


def canonical_legal_ir_frozen_tokenizer() -> LegalIRFrozenTokenizer:
    """Return the process-local canonical freeze.  Vocabulary is immutable."""

    return LegalIRFrozenTokenizer.canonical()


def _family_output_type(family: str) -> str:
    mapping = {
        spec.family: spec.output_type for spec in default_legal_ir_production_specs()
    }
    return mapping.get(family, "")


def _chunks(value: str, size: int) -> tuple[str, ...]:
    return tuple(value[index : index + size] for index in range(0, len(value), size))


_CLOSED_VALUE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "family",
        "modality",
        "operator",
        "quantifier",
        "connective",
        "backend",
    }
)


SHARED_LATENT_ARCHITECTURE_ARM = "shared_latent"
SHARED_ENCODER_TYPED_HEAD_ARCHITECTURE_ARM = "shared_encoder_typed_head"
COMPATIBLE_ARCHITECTURE_ARMS = (
    SHARED_LATENT_ARCHITECTURE_ARM,
    SHARED_ENCODER_TYPED_HEAD_ARCHITECTURE_ARM,
)
COMPATIBLE_ARCHITECTURE_SCHEMA_VERSION = "legal-ir-compatible-architecture-v1"
COMPATIBLE_ARCHITECTURE_INIT_CHECKPOINT_SCHEMA = "IRCompatibleArchitectureInitCheckpoint@1"
SHARED_LATENT_ARCHITECTURE_VERSION = "shared_latent_v1"
SHARED_ENCODER_TYPED_HEAD_ARCHITECTURE_VERSION = "shared_encoder_typed_head_v1"
COMPATIBLE_ARCHITECTURE_DEFAULT_LATENT_DIM = 16
COMPATIBLE_ARCHITECTURE_DEFAULT_HIDDEN_DIM = 16
COMPATIBLE_ARCHITECTURE_DEFAULT_MAX_SEQ_LEN = 32
COMPATIBLE_ARCHITECTURE_OUTPUT_HEADS = (
    "family",
    "view",
    "reconstruction",
    "uncertainty",
)
MODEL_LEGACY_1_IDENTITY = "MODEL-LEGACY-1"
COMPATIBLE_LEGACY_ARCHITECTURE_VERSIONS = frozenset(
    {
        "legacy_dense_v1",
        "proof_aware_auxiliary_heads_v2",
        SHARED_LATENT_ARCHITECTURE_VERSION,
        SHARED_ENCODER_TYPED_HEAD_ARCHITECTURE_VERSION,
    }
)


class IncompatibleLegacyWarmStartError(ValueError):
    """Raised when MODEL-LEGACY-1 fails compatibility or quarantine."""


def evaluate_legacy_warm_start(
    *,
    compatibility_passed: bool,
    quarantine_passed: bool,
    architecture_version: str = "",
    legacy_identity: str = MODEL_LEGACY_1_IDENTITY,
) -> dict[str, Any]:
    """Admit MODEL-LEGACY-1 only as a non-authoritative warm start."""

    compatible = bool(compatibility_passed)
    quarantined = bool(quarantine_passed)
    allowed = compatible and quarantined
    if architecture_version and architecture_version not in COMPATIBLE_LEGACY_ARCHITECTURE_VERSIONS:
        allowed = False
        reason = "architecture version is not in the compatible set"
    elif not compatible:
        reason = "legacy compatibility gate failed"
    elif not quarantined:
        reason = "legacy quarantine gate failed"
    else:
        reason = "warm-start admitted without promotion or semantic authority"
    return {
        "allowed": allowed,
        "architecture_version": architecture_version,
        "authority": False,
        "identity": legacy_identity,
        "promoted": False,
        "reason": reason,
    }


def require_legacy_warm_start(**kwargs: Any) -> dict[str, Any]:
    report = evaluate_legacy_warm_start(**kwargs)
    if not report["allowed"]:
        raise IncompatibleLegacyWarmStartError(str(report["reason"]))
    return report


def _compatible_architecture_arm_name(value: Optional[str]) -> str:
    arm = str(value or SHARED_LATENT_ARCHITECTURE_ARM).strip()
    if arm not in COMPATIBLE_ARCHITECTURE_ARMS:
        raise ValueError(
            "architecture arm must be one of " + ", ".join(COMPATIBLE_ARCHITECTURE_ARMS)
        )
    return arm


def _architecture_version_for_arm(arm: str) -> str:
    if arm == SHARED_ENCODER_TYPED_HEAD_ARCHITECTURE_ARM:
        return SHARED_ENCODER_TYPED_HEAD_ARCHITECTURE_VERSION
    return SHARED_LATENT_ARCHITECTURE_VERSION


def _zeros(size: int) -> list[float]:
    return [0.0] * int(size)


def _seeded_vector(size: int, *, seed: int, salt: str) -> list[float]:
    digest = hashlib.sha256(f"{int(seed)}:{salt}".encode("utf-8")).digest()
    values: list[float] = []
    block = digest
    while len(values) < size:
        for index in range(0, len(block), 4):
            chunk = block[index : index + 4]
            if len(chunk) < 4 or len(values) >= size:
                break
            raw = int.from_bytes(chunk, "big") / 4294967295.0
            values.append((raw * 2.0 - 1.0) * 0.05)
        block = hashlib.sha256(block).digest()
    return values


def _seeded_matrix(rows: int, cols: int, *, seed: int, salt: str) -> list[list[float]]:
    return [
        _seeded_vector(cols, seed=seed, salt=f"{salt}:{row}")
        for row in range(int(rows))
    ]


def _vec_add(left: Sequence[float], right: Sequence[float]) -> list[float]:
    return [float(a) + float(b) for a, b in zip(left, right)]


def _vec_sub(left: Sequence[float], right: Sequence[float]) -> list[float]:
    return [float(a) - float(b) for a, b in zip(left, right)]


def _vec_scale(values: Sequence[float], scale: float) -> list[float]:
    return [float(value) * float(scale) for value in values]


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(float(a) * float(b) for a, b in zip(left, right))


def _mat_vec(matrix: Sequence[Sequence[float]], vector: Sequence[float]) -> list[float]:
    return [_dot(row, vector) for row in matrix]


def _transpose_mat_vec(
    matrix: Sequence[Sequence[float]],
    vector: Sequence[float],
) -> list[float]:
    if not matrix:
        return []
    width = len(matrix[0])
    result = [0.0] * width
    for row_index, row in enumerate(matrix):
        scale = float(vector[row_index])
        for col_index, value in enumerate(row):
            result[col_index] += float(value) * scale
    return result


def _outer(left: Sequence[float], right: Sequence[float]) -> list[list[float]]:
    return [[float(a) * float(b) for b in right] for a in left]


def _matrix_add(
    left: Sequence[Sequence[float]],
    right: Sequence[Sequence[float]],
) -> list[list[float]]:
    return [_vec_add(a, b) for a, b in zip(left, right)]


def _matrix_scale(matrix: Sequence[Sequence[float]], scale: float) -> list[list[float]]:
    return [_vec_scale(row, scale) for row in matrix]


def _softmax_vector(logits: Sequence[float]) -> list[float]:
    if not logits:
        return []
    peak = max(float(value) for value in logits)
    exps = [math.exp(float(value) - peak) for value in logits]
    total = sum(exps) or 1.0
    return [value / total for value in exps]


def _sigmoid_scalar(value: float) -> float:
    clipped = max(-30.0, min(30.0, float(value)))
    return 1.0 / (1.0 + math.exp(-clipped))


def _entropy(probabilities: Sequence[float]) -> float:
    total = 0.0
    for probability in probabilities:
        if probability > 0.0:
            total -= float(probability) * math.log(float(probability))
    return total


def _l2_norm(values: Sequence[float]) -> float:
    return math.sqrt(sum(float(value) * float(value) for value in values))


def _matrix_l2_norm(matrix: Sequence[Sequence[float]]) -> float:
    return math.sqrt(
        sum(float(value) * float(value) for row in matrix for value in row)
    )


def _copy_matrix(matrix: Sequence[Sequence[float]]) -> list[list[float]]:
    return [list(row) for row in matrix]


def _copy_vector(values: Sequence[float]) -> list[float]:
    return [float(value) for value in values]


@dataclass
class CompatibleArchitectureConfig:
    """Smallest compatible experiment-arm configuration."""

    arm: str = SHARED_LATENT_ARCHITECTURE_ARM
    latent_dim: int = COMPATIBLE_ARCHITECTURE_DEFAULT_LATENT_DIM
    hidden_dim: int = COMPATIBLE_ARCHITECTURE_DEFAULT_HIDDEN_DIM
    max_seq_len: int = COMPATIBLE_ARCHITECTURE_DEFAULT_MAX_SEQ_LEN
    seed: int = 0
    families: tuple[str, ...] = LEGAL_IR_GRAMMAR_FAMILIES
    views: tuple[str, ...] = (
        "deontic.ir",
        "modal.frame_logic",
        "TDFOL.prover",
        "knowledge_graphs.neo4j_compat",
        "CEC.native",
        "external_provers.router",
        "temporal.ir",
        "provenance.ir",
        "decompiler.plan",
    )

    def __post_init__(self) -> None:
        self.arm = _compatible_architecture_arm_name(self.arm)
        self.latent_dim = max(2, int(self.latent_dim))
        self.hidden_dim = max(2, int(self.hidden_dim))
        self.max_seq_len = max(4, int(self.max_seq_len))
        self.seed = int(self.seed)
        self.families = tuple(str(item) for item in self.families)
        self.views = tuple(str(item) for item in self.views)

    @property
    def representation_dim(self) -> int:
        if self.arm == SHARED_ENCODER_TYPED_HEAD_ARCHITECTURE_ARM:
            return int(self.hidden_dim)
        return int(self.latent_dim)

    @property
    def architecture_version(self) -> str:
        return _architecture_version_for_arm(self.arm)

    def to_dict(self) -> dict[str, Any]:
        return {
            "architecture_version": self.architecture_version,
            "arm": self.arm,
            "families": list(self.families),
            "hidden_dim": int(self.hidden_dim),
            "latent_dim": int(self.latent_dim),
            "max_seq_len": int(self.max_seq_len),
            "seed": int(self.seed),
            "views": list(self.views),
        }


class CompatibleLearnedArchitecture:
    """Runnable shared-latent or shared-encoder/typed-head experiment arm.

    Neither arm is a promotion winner.  Proof labels stay nondifferentiable.
    The frozen tokenizer is the only vocabulary authority.
    """

    def __init__(
        self,
        *,
        config: Optional[CompatibleArchitectureConfig] = None,
        tokenizer: Optional[LegalIRFrozenTokenizer] = None,
        parameters: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self.config = config or CompatibleArchitectureConfig()
        self.tokenizer = tokenizer or LegalIRFrozenTokenizer.canonical()
        if not self.tokenizer.frozen:
            raise FrozenVocabularyMutationError(
                "compatible architectures require a frozen tokenizer"
            )
        self.families = tuple(self.config.families)
        self.views = tuple(self.config.views)
        self.vocab_size = int(self.tokenizer.vocabulary_size)
        self.dim = int(self.config.representation_dim)
        self.parameters = self._initialize_parameters(parameters)

    def _initialize_parameters(
        self,
        parameters: Optional[Mapping[str, Any]],
    ) -> dict[str, Any]:
        if parameters:
            return self._hydrate_parameters(parameters)
        seed = self.config.seed
        arm = self.config.arm
        typed_heads: dict[str, dict[str, Any]] = {}
        if self.config.arm == SHARED_ENCODER_TYPED_HEAD_ARCHITECTURE_ARM:
            for family in self.families:
                typed_heads[family] = {
                    "bias": _seeded_vector(
                        len(self.families),
                        seed=seed,
                        salt=f"{arm}:typed:{family}:bias",
                    ),
                    "uncertainty_bias": _seeded_vector(
                        1,
                        seed=seed,
                        salt=f"{arm}:typed:{family}:uncertainty_bias",
                    )[0],
                    "uncertainty_weight": _seeded_vector(
                        self.dim,
                        seed=seed,
                        salt=f"{arm}:typed:{family}:uncertainty_weight",
                    ),
                    "weight": _seeded_matrix(
                        len(self.families),
                        self.dim,
                        seed=seed,
                        salt=f"{arm}:typed:{family}:weight",
                    ),
                }
        return {
            "embedding": _seeded_matrix(
                self.vocab_size, self.dim, seed=seed, salt=f"{arm}:embedding"
            ),
            "encoder_bias": _seeded_vector(self.dim, seed=seed, salt=f"{arm}:encoder_bias"),
            "family_bias": _seeded_vector(
                len(self.families), seed=seed, salt=f"{arm}:family_bias"
            ),
            "family_weight": _seeded_matrix(
                len(self.families), self.dim, seed=seed, salt=f"{arm}:family_weight"
            ),
            "reconstruction_bias": _seeded_vector(
                self.vocab_size, seed=seed, salt=f"{arm}:reconstruction_bias"
            ),
            "reconstruction_weight": _seeded_matrix(
                self.vocab_size,
                self.dim,
                seed=seed,
                salt=f"{arm}:reconstruction_weight",
            ),
            "typed_heads": typed_heads,
            "uncertainty_bias": _seeded_vector(
                1, seed=seed, salt=f"{arm}:uncertainty_bias"
            )[0],
            "uncertainty_weight": _seeded_vector(
                self.dim, seed=seed, salt=f"{arm}:uncertainty_weight"
            ),
            "view_bias": _seeded_vector(len(self.views), seed=seed, salt=f"{arm}:view_bias"),
            "view_weight": _seeded_matrix(
                len(self.views), self.dim, seed=seed, salt=f"{arm}:view_weight"
            ),
        }

    def _hydrate_parameters(self, parameters: Mapping[str, Any]) -> dict[str, Any]:
        typed_heads = {}
        raw_heads = dict(parameters.get("typed_heads") or {})
        for family, payload in raw_heads.items():
            typed_heads[str(family)] = {
                "bias": [float(value) for value in payload["bias"]],
                "uncertainty_bias": float(payload["uncertainty_bias"]),
                "uncertainty_weight": [
                    float(value) for value in payload["uncertainty_weight"]
                ],
                "weight": [[float(value) for value in row] for row in payload["weight"]],
            }
        return {
            "embedding": [[float(value) for value in row] for row in parameters["embedding"]],
            "encoder_bias": [float(value) for value in parameters["encoder_bias"]],
            "family_bias": [float(value) for value in parameters["family_bias"]],
            "family_weight": [
                [float(value) for value in row] for row in parameters["family_weight"]
            ],
            "reconstruction_bias": [
                float(value) for value in parameters["reconstruction_bias"]
            ],
            "reconstruction_weight": [
                [float(value) for value in row]
                for row in parameters["reconstruction_weight"]
            ],
            "typed_heads": typed_heads,
            "uncertainty_bias": float(parameters["uncertainty_bias"]),
            "uncertainty_weight": [
                float(value) for value in parameters["uncertainty_weight"]
            ],
            "view_bias": [float(value) for value in parameters["view_bias"]],
            "view_weight": [
                [float(value) for value in row] for row in parameters["view_weight"]
            ],
        }

    def tokenize(
        self,
        structured_ir: Any,
        *,
        family: str = "",
        source_text: str = "",
    ) -> LegalIRTokenization:
        return self.tokenizer.encode_canonical(
            structured_ir,
            family=family,
            source_text=source_text,
            max_length=self.config.max_seq_len,
        )

    def encode_ids(self, token_ids: Sequence[int]) -> list[float]:
        if not token_ids:
            return list(self.parameters["encoder_bias"])
        pooled = _zeros(self.dim)
        count = 0
        for token_id in token_ids:
            if int(token_id) == self.tokenizer.pad_id:
                continue
            pooled = _vec_add(pooled, self.parameters["embedding"][int(token_id)])
            count += 1
        if count:
            pooled = _vec_scale(pooled, 1.0 / float(count))
        return _vec_add(pooled, self.parameters["encoder_bias"])

    def _family_index(self, family: str) -> int:
        resolved = str(family or self.families[0])
        if resolved in self.families:
            return self.families.index(resolved)
        return 0

    def _view_index(self, view: str) -> int:
        resolved = str(view or self.views[0])
        if resolved in self.views:
            return self.views.index(resolved)
        return 0

    def _conditioning_vector(
        self,
        *,
        family: str,
        view: str,
        source_text: str,
    ) -> list[float]:
        values = _zeros(self.dim)
        values[self._family_index(family) % self.dim] += 1.0
        values[self._view_index(view) % self.dim] += 0.5
        if source_text:
            digest = hashlib.sha256(
                " ".join(str(source_text).split()).encode("utf-8")
            ).digest()
            for offset in range(min(8, self.dim)):
                values[offset] += ((digest[offset] / 255.0) * 2.0 - 1.0) * 0.05
        return values

    def _select_family_head(self, family: str) -> tuple[list[list[float]], list[float]]:
        if self.config.arm == SHARED_ENCODER_TYPED_HEAD_ARCHITECTURE_ARM:
            head = self.parameters["typed_heads"][self.families[self._family_index(family)]]
            return head["weight"], head["bias"]
        return self.parameters["family_weight"], self.parameters["family_bias"]

    def _select_uncertainty_head(self, family: str) -> tuple[list[float], float]:
        if self.config.arm == SHARED_ENCODER_TYPED_HEAD_ARCHITECTURE_ARM:
            head = self.parameters["typed_heads"][self.families[self._family_index(family)]]
            return head["uncertainty_weight"], float(head["uncertainty_bias"])
        return (
            self.parameters["uncertainty_weight"],
            float(self.parameters["uncertainty_bias"]),
        )

    def forward(
        self,
        structured_ir: Any,
        *,
        family: str = "",
        source_text: str = "",
        view: str = "",
        target_family: str = "",
        proof_label: str = "",
    ) -> dict[str, Any]:
        tokenization = self.tokenize(
            structured_ir,
            family=family,
            source_text=source_text,
        )
        token_ids = self.tokenizer.pad_ids(
            tokenization.token_ids,
            max_length=self.config.max_seq_len,
        )
        hidden = self.encode_ids(token_ids)
        conditioning = self._conditioning_vector(
            family=tokenization.family or family,
            view=view or f"{tokenization.family or family}.ir",
            source_text=source_text,
        )
        latent = _vec_add(hidden, conditioning)
        latent_norm = _l2_norm(latent) or 1.0
        latent = _vec_scale(latent, 1.0 / latent_norm)
        family_weight, family_bias = self._select_family_head(tokenization.family or family)
        family_logits = _vec_add(_mat_vec(family_weight, latent), family_bias)
        family_probabilities = _softmax_vector(family_logits)
        view_logits = _vec_add(
            _mat_vec(self.parameters["view_weight"], latent),
            self.parameters["view_bias"],
        )
        view_probabilities = _softmax_vector(view_logits)
        reconstruction_logits = _vec_add(
            _mat_vec(self.parameters["reconstruction_weight"], latent),
            self.parameters["reconstruction_bias"],
        )
        uncertainty_weight, uncertainty_bias = self._select_uncertainty_head(
            tokenization.family or family
        )
        aleatoric = _sigmoid_scalar(_dot(uncertainty_weight, latent) + uncertainty_bias)
        epistemic = _entropy(family_probabilities)
        confidence = max(family_probabilities) if family_probabilities else 0.0
        predicted_family = (
            self.families[family_probabilities.index(confidence)]
            if family_probabilities
            else ""
        )
        target = str(target_family or tokenization.family or family or self.families[0])
        target_index = self._family_index(target)
        target_one_hot = [0.0] * len(self.families)
        target_one_hot[target_index] = 1.0
        loss = -math.log(max(family_probabilities[target_index], 1.0e-12))
        return {
            "accepted": tokenization.accepted,
            "aleatoric_uncertainty": round(float(aleatoric), 12),
            "architecture_version": self.config.architecture_version,
            "arm": self.config.arm,
            "canonical_token_count": tokenization.canonical_token_count,
            "conditioning": {
                "family": tokenization.family or family,
                "proof_label": str(proof_label or ""),
                "proof_label_differentiable": False,
                "source_surface_separated": True,
                "view": view or f"{tokenization.family or family}.ir",
            },
            "confidence": round(float(confidence), 12),
            "epistemic_uncertainty": round(float(epistemic), 12),
            "family_logits": [round(float(value), 12) for value in family_logits],
            "family_probabilities": [
                round(float(value), 12) for value in family_probabilities
            ],
            "heads": {
                "family": {
                    "kind": "categorical",
                    "output_size": len(self.families),
                    "shared": self.config.arm == SHARED_LATENT_ARCHITECTURE_ARM,
                },
                "reconstruction": {
                    "kind": "token_softmax",
                    "output_size": self.vocab_size,
                    "shared": True,
                },
                "uncertainty": {
                    "kind": "aleatoric_epistemic",
                    "output_size": 2,
                    "shared": self.config.arm == SHARED_LATENT_ARCHITECTURE_ARM,
                },
                "view": {
                    "kind": "categorical",
                    "output_size": len(self.views),
                    "shared": True,
                },
            },
            "hidden": [round(float(value), 12) for value in hidden],
            "latent": [round(float(value), 12) for value in latent],
            "latent_normalized": True,
            "loss": round(float(loss), 12),
            "predicted_family": predicted_family,
            "reconstruction_logits": [
                round(float(value), 12) for value in reconstruction_logits
            ],
            "schema_version": COMPATIBLE_ARCHITECTURE_SCHEMA_VERSION,
            "shapes": {
                "family_logits": [len(self.families)],
                "latent": [self.dim],
                "reconstruction_logits": [self.vocab_size],
                "token_ids": [self.config.max_seq_len],
                "view_logits": [len(self.views)],
            },
            "source_surface_token_count": tokenization.source_surface_token_count,
            "target_family": target,
            "target_one_hot": target_one_hot,
            "token_class_counts": tokenization.token_class_histogram(),
            "token_ids": token_ids,
            "tokenization": tokenization.to_dict(),
            "tokenizer_vocabulary_cid": self.tokenizer.vocabulary_cid,
            "view_logits": [round(float(value), 12) for value in view_logits],
            "view_probabilities": [
                round(float(value), 12) for value in view_probabilities
            ],
            "winner": False,
        }

    def backward(self, forward_result: Mapping[str, Any]) -> dict[str, Any]:
        latent = [float(value) for value in forward_result["latent"]]
        probabilities = [float(value) for value in forward_result["family_probabilities"]]
        target = [float(value) for value in forward_result["target_one_hot"]]
        family = str(forward_result.get("conditioning", {}).get("family") or "")
        family_weight, _family_bias = self._select_family_head(family)
        d_logits = _vec_sub(probabilities, target)
        d_weight = _outer(d_logits, latent)
        d_bias = list(d_logits)
        d_latent = _transpose_mat_vec(family_weight, d_logits)
        token_ids = [int(value) for value in forward_result["token_ids"]]
        active = [token_id for token_id in token_ids if token_id != self.tokenizer.pad_id]
        scale = 1.0 / float(len(active) or 1)
        d_embedding = [_zeros(self.dim) for _ in range(self.vocab_size)]
        for token_id in active:
            d_embedding[token_id] = _vec_add(
                d_embedding[token_id],
                _vec_scale(d_latent, scale),
            )
        return {
            "d_embedding_norm": round(_matrix_l2_norm(d_embedding), 12),
            "d_family_bias": [round(float(value), 12) for value in d_bias],
            "d_family_weight": [
                [round(float(value), 12) for value in row] for row in d_weight
            ],
            "d_latent": [round(float(value), 12) for value in d_latent],
            "gradient_norm": round(
                math.sqrt(
                    _matrix_l2_norm(d_weight) ** 2
                    + _l2_norm(d_bias) ** 2
                    + _l2_norm(d_latent) ** 2
                ),
                12,
            ),
            "proof_in_gradient_path": False,
        }

    def step(
        self,
        structured_ir: Any,
        *,
        family: str = "",
        source_text: str = "",
        target_family: str = "",
        learning_rate: float = 0.05,
    ) -> dict[str, Any]:
        forward_result = self.forward(
            structured_ir,
            family=family,
            source_text=source_text,
            target_family=target_family,
        )
        gradients = self.backward(forward_result)
        family_name = str(forward_result["conditioning"]["family"] or family)
        family_weight, family_bias = self._select_family_head(family_name)
        updated_weight = _matrix_add(
            family_weight,
            _matrix_scale(gradients["d_family_weight"], -float(learning_rate)),
        )
        updated_bias = _vec_add(
            family_bias,
            _vec_scale(gradients["d_family_bias"], -float(learning_rate)),
        )
        if self.config.arm == SHARED_ENCODER_TYPED_HEAD_ARCHITECTURE_ARM:
            head = self.parameters["typed_heads"][
                self.families[self._family_index(family_name)]
            ]
            head["weight"] = updated_weight
            head["bias"] = updated_bias
        else:
            self.parameters["family_weight"] = updated_weight
            self.parameters["family_bias"] = updated_bias
        updated = self.forward(
            structured_ir,
            family=family,
            source_text=source_text,
            target_family=target_family,
        )
        return {
            "after": updated,
            "before": forward_result,
            "gradients": gradients,
            "loss_delta": round(float(updated["loss"]) - float(forward_result["loss"]), 12),
        }

    def parameter_count(self) -> int:
        count = 0
        count += self.vocab_size * self.dim
        count += self.dim
        count += len(self.families) * self.dim + len(self.families)
        count += len(self.views) * self.dim + len(self.views)
        count += self.vocab_size * self.dim + self.vocab_size
        count += self.dim + 1
        if self.config.arm == SHARED_ENCODER_TYPED_HEAD_ARCHITECTURE_ARM:
            count += len(self.families) * (
                len(self.families) * self.dim + len(self.families) + self.dim + 1
            )
        return int(count)

    def parameter_resource_estimate(self) -> dict[str, Any]:
        parameter_count = self.parameter_count()
        return {
            "arm": self.config.arm,
            "bytes_fp32": int(parameter_count * 4),
            "device": "cpu",
            "estimated_forward_flops": int(
                self.config.max_seq_len * self.dim
                + self.dim * (len(self.families) + len(self.views) + self.vocab_size)
            ),
            "gpu_required": False,
            "hidden_dim": self.config.hidden_dim,
            "latent_dim": self.config.latent_dim,
            "max_seq_len": self.config.max_seq_len,
            "parameter_count": parameter_count,
            "tokenizer_vocabulary_size": self.vocab_size,
        }

    def architecture_manifest(self) -> dict[str, Any]:
        return {
            "architecture_version": self.config.architecture_version,
            "arm": self.config.arm,
            "compatible_with_advisor": True,
            "config": self.config.to_dict(),
            "heads": list(COMPATIBLE_ARCHITECTURE_OUTPUT_HEADS),
            "legacy_promoted": False,
            "output_heads": {
                "conditioning": ["family", "view", "source_span_hash"],
                "family": list(self.families),
                "uncertainty": ["aleatoric", "epistemic"],
                "view": list(self.views),
            },
            "parameter_resource_estimate": self.parameter_resource_estimate(),
            "schema_version": COMPATIBLE_ARCHITECTURE_SCHEMA_VERSION,
            "tokenizer_schema_version": LEGAL_IR_FROZEN_TOKENIZER_SCHEMA_VERSION,
            "tokenizer_vocabulary_cid": self.tokenizer.vocabulary_cid,
            "tokenizer_vocabulary_sha256": self.tokenizer.vocabulary_sha256,
            "winner": False,
        }

    def initialization_checkpoint(self) -> dict[str, Any]:
        return {
            "architecture_manifest": self.architecture_manifest(),
            "architecture_version": self.config.architecture_version,
            "arm": self.config.arm,
            "legacy_promoted": False,
            "parameters": self.parameters_to_dict(),
            "schema": COMPATIBLE_ARCHITECTURE_INIT_CHECKPOINT_SCHEMA,
            "schema_version": COMPATIBLE_ARCHITECTURE_SCHEMA_VERSION,
            "seed": self.config.seed,
            "tokenizer_vocabulary_cid": self.tokenizer.vocabulary_cid,
            "winner": False,
        }

    def parameters_to_dict(self) -> dict[str, Any]:
        typed_heads = {
            family: {
                "bias": _copy_vector(payload["bias"]),
                "uncertainty_bias": float(payload["uncertainty_bias"]),
                "uncertainty_weight": _copy_vector(payload["uncertainty_weight"]),
                "weight": _copy_matrix(payload["weight"]),
            }
            for family, payload in self.parameters["typed_heads"].items()
        }
        return {
            "embedding": _copy_matrix(self.parameters["embedding"]),
            "encoder_bias": _copy_vector(self.parameters["encoder_bias"]),
            "family_bias": _copy_vector(self.parameters["family_bias"]),
            "family_weight": _copy_matrix(self.parameters["family_weight"]),
            "reconstruction_bias": _copy_vector(self.parameters["reconstruction_bias"]),
            "reconstruction_weight": _copy_matrix(self.parameters["reconstruction_weight"]),
            "typed_heads": typed_heads,
            "uncertainty_bias": float(self.parameters["uncertainty_bias"]),
            "uncertainty_weight": _copy_vector(self.parameters["uncertainty_weight"]),
            "view_bias": _copy_vector(self.parameters["view_bias"]),
            "view_weight": _copy_matrix(self.parameters["view_weight"]),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": self.config.to_dict(),
            "parameters": self.parameters_to_dict(),
            "schema_version": COMPATIBLE_ARCHITECTURE_SCHEMA_VERSION,
            "tokenizer": self.tokenizer.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CompatibleLearnedArchitecture":
        config_payload = dict(payload.get("config") or {})
        default_views = CompatibleArchitectureConfig().views
        config = CompatibleArchitectureConfig(
            arm=str(config_payload.get("arm") or SHARED_LATENT_ARCHITECTURE_ARM),
            latent_dim=int(
                config_payload.get("latent_dim")
                or COMPATIBLE_ARCHITECTURE_DEFAULT_LATENT_DIM
            ),
            hidden_dim=int(
                config_payload.get("hidden_dim")
                or COMPATIBLE_ARCHITECTURE_DEFAULT_HIDDEN_DIM
            ),
            max_seq_len=int(
                config_payload.get("max_seq_len")
                or COMPATIBLE_ARCHITECTURE_DEFAULT_MAX_SEQ_LEN
            ),
            seed=int(config_payload.get("seed") or 0),
            families=tuple(config_payload.get("families") or LEGAL_IR_GRAMMAR_FAMILIES),
            views=tuple(config_payload.get("views") or default_views),
        )
        tokenizer_payload = payload.get("tokenizer")
        tokenizer = (
            LegalIRFrozenTokenizer.from_dict(tokenizer_payload)
            if isinstance(tokenizer_payload, Mapping)
            else LegalIRFrozenTokenizer.canonical()
        )
        return cls(
            config=config,
            tokenizer=tokenizer,
            parameters=payload.get("parameters"),
        )


def build_compatible_learned_architecture(
    arm: str = SHARED_LATENT_ARCHITECTURE_ARM,
    *,
    tokenizer: Optional[LegalIRFrozenTokenizer] = None,
    seed: int = 0,
    latent_dim: int = COMPATIBLE_ARCHITECTURE_DEFAULT_LATENT_DIM,
    hidden_dim: int = COMPATIBLE_ARCHITECTURE_DEFAULT_HIDDEN_DIM,
    max_seq_len: int = COMPATIBLE_ARCHITECTURE_DEFAULT_MAX_SEQ_LEN,
) -> CompatibleLearnedArchitecture:
    return CompatibleLearnedArchitecture(
        config=CompatibleArchitectureConfig(
            arm=arm,
            latent_dim=latent_dim,
            hidden_dim=hidden_dim,
            max_seq_len=max_seq_len,
            seed=seed,
        ),
        tokenizer=tokenizer or LegalIRFrozenTokenizer.canonical(),
    )


def compatible_architecture_suite(
    *,
    seed: int = 0,
    tokenizer: Optional[LegalIRFrozenTokenizer] = None,
) -> dict[str, Any]:
    """Expose both runnable arms without choosing a winner or writing files."""

    frozen = tokenizer or LegalIRFrozenTokenizer.canonical()
    arms = {
        name: build_compatible_learned_architecture(name, tokenizer=frozen, seed=seed)
        for name in COMPATIBLE_ARCHITECTURE_ARMS
    }
    return {
        "arms": {
            name: architecture.architecture_manifest() for name, architecture in arms.items()
        },
        "initialization_roots": {
            name: architecture.initialization_checkpoint()
            for name, architecture in arms.items()
        },
        "instances": arms,
        "legacy_promoted": False,
        "legacy_warm_start": evaluate_legacy_warm_start(
            compatibility_passed=False,
            quarantine_passed=False,
        ),
        "parameter_resource_estimates": {
            name: architecture.parameter_resource_estimate()
            for name, architecture in arms.items()
        },
        "schema_version": COMPATIBLE_ARCHITECTURE_SCHEMA_VERSION,
        "tokenizer_vocabulary_cid": frozen.vocabulary_cid,
        "winner": False,
    }


def compatible_architecture_manifests(
    *,
    seed: int = 0,
    tokenizer: Optional[LegalIRFrozenTokenizer] = None,
) -> dict[str, Any]:
    """Return serializable manifests, init roots, and resource estimates."""

    suite = compatible_architecture_suite(seed=seed, tokenizer=tokenizer)
    return {
        "arms": suite["arms"],
        "initialization_roots": suite["initialization_roots"],
        "legacy_promoted": False,
        "parameter_resource_estimates": suite["parameter_resource_estimates"],
        "schema_version": suite["schema_version"],
        "tokenizer_vocabulary_cid": suite["tokenizer_vocabulary_cid"],
        "winner": False,
    }


def advisor_architecture_version(autoencoder: Any) -> str:
    """Read the existing advisor architecture version without mutating it."""

    if autoencoder is None:
        return ""
    state = getattr(autoencoder, "state", None)
    version = getattr(state, "architecture_version", "") or getattr(
        autoencoder, "architecture_version", ""
    )
    return str(version or "").strip()


def extend_existing_advisor_architectures(
    autoencoder: Any = None,
    *,
    seed: int = 0,
    tokenizer: Optional[LegalIRFrozenTokenizer] = None,
) -> dict[str, Any]:
    """Extend the existing modal-autoencoder advisor into both experiment arms.

    The advisor is not mutated, MODEL-LEGACY-1 is not promoted, and neither
    arm is recorded as a winner.
    """

    frozen = tokenizer or LegalIRFrozenTokenizer.canonical()
    suite = compatible_architecture_suite(seed=seed, tokenizer=frozen)
    advisor_version = advisor_architecture_version(autoencoder)
    compatible_with_advisor = (not advisor_version) or (
        advisor_version in COMPATIBLE_LEGACY_ARCHITECTURE_VERSIONS
    )
    return {
        "advisor_architecture_version": advisor_version or None,
        "advisor_extended": autoencoder is not None,
        "advisor_mutated": False,
        "arms": suite["arms"],
        "compatible_with_advisor": compatible_with_advisor,
        "initialization_roots": suite["initialization_roots"],
        "instances": suite["instances"],
        "legacy_promoted": False,
        "legacy_warm_start": evaluate_legacy_warm_start(
            compatibility_passed=False,
            quarantine_passed=False,
        ),
        "parameter_resource_estimates": suite["parameter_resource_estimates"],
        "schema_version": suite["schema_version"],
        "tokenizer_vocabulary_cid": frozen.vocabulary_cid,
        "winner": False,
    }


__all__ = [
    "COMPATIBLE_ARCHITECTURE_ARMS",
    "COMPATIBLE_ARCHITECTURE_INIT_CHECKPOINT_SCHEMA",
    "COMPATIBLE_ARCHITECTURE_SCHEMA_VERSION",
    "COMPATIBLE_LEGACY_ARCHITECTURE_VERSIONS",
    "CompatibleArchitectureConfig",
    "CompatibleLearnedArchitecture",
    "ConstrainedLegalIRDecode",
    "FrozenVocabularyMutationError",
    "IncompatibleLegacyWarmStartError",
    "LEGAL_IR_CANONICAL_VOCABULARY_CID",
    "LEGAL_IR_CANONICAL_VOCABULARY_SIZE",
    "LEGAL_IR_CLOSED_TOKEN_CLASSES",
    "LEGAL_IR_CONSTRAINED_DECODER_INTERFACE",
    "LEGAL_IR_CONSTRAINED_DECODER_SCHEMA",
    "LEGAL_IR_CONSTRAINT_MASK_NAMES",
    "LEGAL_IR_DECODE_FALLBACKS",
    "LEGAL_IR_FROZEN_TOKENIZER_INTERFACE",
    "LEGAL_IR_FROZEN_TOKENIZER_SCHEMA_VERSION",
    "LEGAL_IR_FROZEN_VOCABULARY_SCHEMA",
    "LEGAL_IR_GRAMMAR_DECODER_SCHEMA_VERSION",
    "LEGAL_IR_GRAMMAR_FAMILIES",
    "LEGAL_IR_IDENTIFIER_BUCKET_COUNT",
    "LEGAL_IR_MAX_BEAM_WIDTH",
    "LEGAL_IR_MAX_DECODE_STEPS",
    "LEGAL_IR_TOKEN_CLASSES",
    "LegalIRBeamHypothesis",
    "LegalIRConstrainedDecodeConfig",
    "LegalIRConstrainedTokenDecode",
    "LegalIRConstraintBypassError",
    "LegalIRConstraintMasks",
    "LegalIRConstraintRejectionTelemetry",
    "LegalIRFrozenTokenizer",
    "LegalIRGoldPathAdmission",
    "LegalIRGrammarDecoder",
    "LegalIRGrammarRejection",
    "LegalIRGrammarValidation",
    "LegalIRProductionSpec",
    "LegalIRProverAdmission",
    "LegalIRToken",
    "LegalIRTokenization",
    "LegalIRVocabEntry",
    "MODEL_LEGACY_1_IDENTITY",
    "SHARED_ENCODER_TYPED_HEAD_ARCHITECTURE_ARM",
    "SHARED_ENCODER_TYPED_HEAD_ARCHITECTURE_VERSION",
    "SHARED_LATENT_ARCHITECTURE_ARM",
    "SHARED_LATENT_ARCHITECTURE_VERSION",
    "UnboundedLegalIRBeamError",
    "UnknownFrozenTokenError",
    "admit_legal_ir_gold_path",
    "advisor_architecture_version",
    "apply_legal_ir_constraint_masks",
    "build_compatible_learned_architecture",
    "canonical_legal_ir_frozen_tokenizer",
    "canonical_legal_ir_grammar_family",
    "compare_constrained_vs_unconstrained_proof_calls",
    "compatible_architecture_manifests",
    "compatible_architecture_suite",
    "constrained_legal_ir_decode",
    "constrained_legal_ir_token_decode",
    "default_legal_ir_frozen_vocabulary",
    "default_legal_ir_production_specs",
    "evaluate_legacy_warm_start",
    "extend_existing_advisor_architectures",
    "gate_legal_ir_prover_call",
    "grammar_metrics_from_validation",
    "grammar_rejection_reason_names",
    "infer_legal_ir_grammar_family",
    "legal_ir_constrained_decode_config",
    "legal_ir_constraint_masks",
    "require_legacy_warm_start",
    "validate_legal_ir_candidate",
]
