"""Typed-deontic adapter for the canonical semantic round-trip boundary.

The production deontic converter deliberately remains unchanged.  This module
only projects its ``LegalNormIR`` records into the closed, scored
``CanonicalRuleIR`` schema used by the composition benchmark.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Final

from benchmarks.semantic_roundtrip.contracts import (
    AllowedAtomVocabulary,
    CanonicalRule,
    CanonicalRuleIR,
    ComponentStatus,
    ConstructorRequest,
    ConstructorResult,
    ContractError,
    FailureReason,
    RoundTripConstructor,
)


TYPED_DEONTIC_CANONICAL_CONSTRUCTOR_INTERFACE: Final = (
    "TypedDeonticCanonicalConstructor@1"
)
_TOKEN_RE: Final = re.compile(r"[a-z0-9]+")


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _tokens(value: object) -> tuple[str, ...]:
    words = _TOKEN_RE.findall(_clean_text(value).lower().replace("_", " "))
    normalized: list[str] = []
    for word in words:
        if len(word) > 4 and word.endswith("ies"):
            word = word[:-3] + "y"
        elif len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        normalized.append(word)
    return tuple(normalized)


def _flatten_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        result: list[str] = []
        for key, item in value.items():
            result.append(str(key))
            result.extend(_flatten_strings(item))
        return result
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        result = []
        for item in value:
            result.extend(_flatten_strings(item))
        return result
    if value is None:
        return []
    return [str(value)]


def _jaccard(left: object, right: object) -> float:
    left_tokens, right_tokens = set(_tokens(left)), set(_tokens(right))
    if not left_tokens and not right_tokens:
        return 1.0
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _best_atom(
    value: object,
    candidates: Sequence[str],
    *,
    allow_empty: bool = False,
    threshold: float = 0.12,
) -> str:
    """Return the same deterministic closed-vocabulary match as the pilot."""

    pieces = _flatten_strings(value)
    text = " ".join(pieces)
    if not _clean_text(text):
        return "" if allow_empty else ""
    scored = sorted(
        (
            (
                max(
                    [_jaccard(text, candidate)]
                    + [_jaccard(piece, candidate) for piece in pieces]
                ),
                candidate,
            )
            for candidate in candidates
        ),
        key=lambda item: (-item[0], item[1]),
    )
    if not scored or scored[0][0] < threshold:
        return ""
    return scored[0][1]


def _map_many(value: object, candidates: Sequence[str]) -> tuple[str, ...]:
    values: list[object]
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        values = list(value)
    elif value is None or value == "" or value == []:
        values = []
    else:
        values = [value]
    return tuple(
        sorted(
            {
                atom
                for item in values
                if (atom := _best_atom(item, candidates))
            }
        )
    )


def _modality_from_text(value: object) -> str:
    text = _clean_text(value).lower()
    if (
        text in {"f", "prohibition", "forbidden"}
        or "prohibit" in text
        or "shall not" in text
        or "must not" in text
    ):
        return "F"
    if text in {"p", "permission", "permitted"} or "permission" in text:
        return "P"
    return "O"


def project_legal_norms(
    norms: Sequence[object],
    vocabulary: AllowedAtomVocabulary,
) -> CanonicalRuleIR:
    """Project supported ``LegalNormIR`` records into exact canonical fields.

    As in the reviewed pilot, a record is supported when its actor and action
    both map into the closed case vocabulary.  An absent or unmatched object
    is represented explicitly by ``""`` and absent qualifier facets by empty
    tuples.  No source spans, native IR, metadata, or decoder records cross the
    canonical boundary.
    """

    if not isinstance(vocabulary, AllowedAtomVocabulary):
        raise ContractError("vocabulary must be AllowedAtomVocabulary")

    rules: list[CanonicalRule] = []
    for norm in norms:
        to_dict = getattr(norm, "to_dict", None)
        if not callable(to_dict):
            raise ContractError("typed deontic norm must provide to_dict()")
        data = to_dict()
        if not isinstance(data, Mapping):
            raise ContractError(
                "typed deontic norm to_dict() must return an object"
            )

        actor = _best_atom(data.get("actor"), vocabulary.actors)
        action = _best_atom(
            [data.get("action"), data.get("action_verb")],
            vocabulary.actions,
        )
        object_atom = _best_atom(
            data.get("action_object"),
            vocabulary.objects,
            allow_empty=True,
        )
        if not actor or not action:
            continue

        rules.append(
            CanonicalRule(
                modality=_modality_from_text(
                    [data.get("modality"), data.get("norm_type")]
                ),
                actor=actor,
                action=action,
                object=object_atom,
                conditions=_map_many(
                    data.get("conditions") or (), vocabulary.qualifiers
                ),
                exceptions=_map_many(
                    data.get("exceptions") or (), vocabulary.qualifiers
                ),
                temporal=_map_many(
                    data.get("temporal_constraints") or (),
                    vocabulary.qualifiers,
                ),
            )
        )

    canonical_ir = CanonicalRuleIR(tuple(rules))
    canonical_ir.validate_vocabulary(vocabulary)
    return canonical_ir


def _failure(
    reason: FailureReason,
    detail: str,
) -> ConstructorResult:
    return ConstructorResult(
        status=ComponentStatus.FAILED,
        failure_reason=reason,
        failure_detail=detail,
    )


class TypedDeonticCanonicalConstructor:
    """Adapt the deterministic typed deontic converter to canonical rule IR."""

    @property
    def identity(self) -> str:
        return TYPED_DEONTIC_CANONICAL_CONSTRUCTOR_INTERFACE

    def construct(self, request: ConstructorRequest) -> ConstructorResult:
        if not isinstance(request, ConstructorRequest):
            return _failure(
                FailureReason.INVALID_OUTPUT,
                "request must be ConstructorRequest",
            )

        try:
            from ipfs_datasets_py.logic.deontic.converter import (
                DeonticConverter,
            )
            from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
        except ImportError:
            return _failure(
                FailureReason.CAPABILITY_UNAVAILABLE,
                "typed deontic converter capability is unavailable",
            )

        try:
            converter = DeonticConverter(
                use_cache=False,
                use_ipfs=False,
                use_ml=False,
                enable_monitoring=False,
                document_type="general",
            )
            converted = converter.convert(request.source_text, use_cache=False)
        except Exception as exc:
            return _failure(
                FailureReason.EXCEPTION,
                f"typed deontic conversion raised {type(exc).__name__}",
            )

        output = getattr(converted, "output", None)
        if output is None:
            return _failure(
                FailureReason.MISSING_OUTPUT,
                "typed deontic converter returned no output",
            )

        elements = list(getattr(output, "parser_elements", ()) or ())
        if not elements:
            return _failure(
                FailureReason.EMPTY_L1,
                "typed deontic converter returned no parser elements",
            )

        try:
            norms = [
                LegalNormIR.from_parser_element(element)
                for element in elements
            ]
            canonical_ir = project_legal_norms(
                norms, request.allowed_atom_vocabulary
            )
        except ContractError as exc:
            return _failure(FailureReason.INVALID_OUTPUT, str(exc))
        except Exception as exc:
            return _failure(
                FailureReason.EXCEPTION,
                f"typed deontic projection raised {type(exc).__name__}",
            )

        if canonical_ir.is_empty:
            return _failure(
                FailureReason.EMPTY_L1,
                "typed deontic records did not map to supported canonical rules",
            )
        return ConstructorResult(
            status=ComponentStatus.SUCCESS,
            canonical_ir=canonical_ir,
        )


assert isinstance(TypedDeonticCanonicalConstructor(), RoundTripConstructor)


__all__ = [
    "TYPED_DEONTIC_CANONICAL_CONSTRUCTOR_INTERFACE",
    "TypedDeonticCanonicalConstructor",
    "project_legal_norms",
]
