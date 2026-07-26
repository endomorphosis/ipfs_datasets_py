"""Canonical constructor over the pinned modal plus full-spaCy frontend.

This module is a benchmark adapter, not a second modal implementation.  It
uses the production :class:`DeterministicModalLogicCodec`, applies the exact
projection used by the preliminary round-trip pilot, and returns only the
seven scored fields in :class:`CanonicalRuleIR`.

The production encoder can deliberately fall back to ``spacy.blank``.  That
behavior remains unchanged, but it is not a valid execution of this benchmark
arm: fallback, model drift, pipeline drift, or a non-spaCy modal parser is
reported as an explicit capability failure.

Source-span evidence is retained in :class:`ModalSpacyConstructorDiagnostics`.
It is deliberately separate from :class:`ConstructorResult`, so it cannot
cross the source-withheld realizer boundary with the canonical IR.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import Enum
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
from benchmarks.semantic_roundtrip_capabilities import (
    SPACY_MODEL,
    SPACY_MODEL_VERSION,
    SPACY_PIPELINE,
)


MODAL_SPACY_CANONICAL_CONSTRUCTOR_INTERFACE: Final = (
    "ModalSpacyCanonicalConstructor@1"
)
DEFAULT_SPACY_MODEL: Final = SPACY_MODEL
DEFAULT_SPACY_MODEL_VERSION: Final = SPACY_MODEL_VERSION
REQUIRED_SPACY_PIPELINE: Final = tuple(SPACY_PIPELINE)
REQUIRED_SPACY_LANGUAGE: Final = "en"
SPACY_MODAL_PARSER: Final = "spacy_modal_codec_v1"
_CODEC_PIPELINE_ADDITIONS: Final = ("sentencizer",)
_TOKEN_RE: Final = re.compile(r"[a-z0-9]+")
_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}")


class ModalSpacyFrontendStatus(str, Enum):
    """Effective frontend disposition for one constructor invocation."""

    FULL_MODEL = "full_model"
    UNAVAILABLE = "unavailable"
    DEGRADED = "degraded"


@dataclass(frozen=True, slots=True)
class SourceSpanDiagnostic:
    """Hash-bound constructor-private source support for one modal formula."""

    formula_id: str
    source_id: str
    start_char: int
    end_char: int
    source_span_sha256: str
    structural_signature: str

    def __post_init__(self) -> None:
        for field in ("formula_id", "source_id", "structural_signature"):
            value = getattr(self, field)
            if not isinstance(value, str):
                raise ContractError(f"{field} must be a string")
        if (
            isinstance(self.start_char, bool)
            or not isinstance(self.start_char, int)
            or self.start_char < 0
            or isinstance(self.end_char, bool)
            or not isinstance(self.end_char, int)
            or self.end_char < self.start_char
        ):
            raise ContractError("source-span offsets are invalid")
        if self.source_span_sha256 and not _SHA256_RE.fullmatch(
            self.source_span_sha256
        ):
            raise ContractError("source_span_sha256 must be empty or SHA-256")

    def to_dict(self) -> dict[str, object]:
        return {
            "formula_id": self.formula_id,
            "source_id": self.source_id,
            "start_char": self.start_char,
            "end_char": self.end_char,
            "source_span_sha256": self.source_span_sha256,
            "structural_signature": self.structural_signature,
        }


@dataclass(frozen=True, slots=True)
class ModalSpacyConstructorDiagnostics:
    """Frontend identity and source evidence kept outside canonical output."""

    frontend_status: ModalSpacyFrontendStatus
    requested_model: str
    effective_model: str
    requested_pipeline: tuple[str, ...]
    effective_pipeline: tuple[str, ...]
    requested_model_version: str
    effective_model_version: str
    language: str
    fallback_used: bool
    parser_backend: str
    source_spans: tuple[SourceSpanDiagnostic, ...] = ()
    detail: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.frontend_status, ModalSpacyFrontendStatus):
            raise ContractError("frontend_status is invalid")
        for field in (
            "requested_model",
            "effective_model",
            "requested_model_version",
            "effective_model_version",
            "language",
            "parser_backend",
        ):
            if not isinstance(getattr(self, field), str):
                raise ContractError(f"{field} must be a string")
        for field in ("requested_pipeline", "effective_pipeline"):
            value = getattr(self, field)
            if (
                not isinstance(value, tuple)
                or not all(isinstance(item, str) for item in value)
            ):
                raise ContractError(f"{field} must be a string tuple")
        if not isinstance(self.fallback_used, bool):
            raise ContractError("fallback_used must be a boolean")
        if not isinstance(self.source_spans, tuple) or not all(
            isinstance(item, SourceSpanDiagnostic)
            for item in self.source_spans
        ):
            raise ContractError(
                "source_spans must contain SourceSpanDiagnostic values"
            )
        if self.detail is not None and (
            not isinstance(self.detail, str) or not self.detail.strip()
        ):
            raise ContractError("diagnostic detail must be nonblank")

    def to_dict(self) -> dict[str, object]:
        return {
            "frontend_status": self.frontend_status.value,
            "requested_model": self.requested_model,
            "effective_model": self.effective_model,
            "requested_pipeline": list(self.requested_pipeline),
            "effective_pipeline": list(self.effective_pipeline),
            "requested_model_version": self.requested_model_version,
            "effective_model_version": self.effective_model_version,
            "language": self.language,
            "fallback_used": self.fallback_used,
            "parser_backend": self.parser_backend,
            "source_spans": [
                item.to_dict() for item in self.source_spans
            ],
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class ModalSpacyConstruction:
    """Constructor result paired with non-realizer diagnostic evidence."""

    result: ConstructorResult
    diagnostics: ModalSpacyConstructorDiagnostics

    def __post_init__(self) -> None:
        if not isinstance(self.result, ConstructorResult):
            raise ContractError("result must be a ConstructorResult")
        if not isinstance(
            self.diagnostics, ModalSpacyConstructorDiagnostics
        ):
            raise ContractError(
                "diagnostics must be ModalSpacyConstructorDiagnostics"
            )


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _tokens(value: object) -> tuple[str, ...]:
    words = _TOKEN_RE.findall(_clean_text(value).lower().replace("_", " "))
    normalized: list[str] = []
    for word in words:
        if len(word) > 4 and word.endswith("ies"):
            word = word[:-3] + "y"
        elif (
            len(word) > 4
            and word.endswith("s")
            and not word.endswith("ss")
        ):
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
    return len(left_tokens & right_tokens) / len(
        left_tokens | right_tokens
    )


def _best_atom(
    value: object,
    candidates: Sequence[str],
    *,
    allow_empty: bool = False,
    threshold: float = 0.12,
) -> str:
    """Return the pilot's deterministic closed-vocabulary atom match."""

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


def _map_many(
    value: object, candidates: Sequence[str]
) -> tuple[str, ...]:
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
    if (
        text in {"p", "permission", "permitted"}
        or "permission" in text
    ):
        return "P"
    return "O"


def project_decompiler_record(
    record: Mapping[str, object],
    vocabulary: AllowedAtomVocabulary,
) -> CanonicalRuleIR:
    """Project a repaired modal record exactly as the existing pilot does."""

    if not isinstance(record, Mapping):
        raise ContractError("modal decompiler record must be an object")
    if not isinstance(vocabulary, AllowedAtomVocabulary):
        raise ContractError("vocabulary must be AllowedAtomVocabulary")
    raw_formulas = record.get("formulas") or ()
    if not isinstance(raw_formulas, Sequence) or isinstance(
        raw_formulas, (str, bytes, bytearray)
    ):
        raise ContractError("modal decompiler formulas must be an array")

    rules: list[CanonicalRule] = []
    for formula in raw_formulas:
        if not isinstance(formula, Mapping):
            continue
        predicate = formula.get("predicate")
        if (
            isinstance(predicate, Mapping)
            and predicate.get("role") not in {None, "", "clause"}
        ):
            # The modal compiler emits condition/exception helper formulas.
            # They are guards, not independently scored legal norms.
            continue
        structure = formula.get("reconstructed_structure")
        structure = structure if isinstance(structure, Mapping) else {}
        roles = structure.get("roles")
        roles = roles if isinstance(roles, Mapping) else {}
        modality = formula.get("modality")
        modality = modality if isinstance(modality, Mapping) else {}
        actor = _best_atom(roles.get("actor"), vocabulary.actors)
        action = _best_atom(
            [roles.get("action"), predicate, formula.get("arguments")],
            vocabulary.actions,
        )
        object_atom = _best_atom(
            roles.get("object"),
            vocabulary.objects,
            allow_empty=True,
        )
        if not actor or not action:
            continue
        rules.append(
            CanonicalRule(
                modality=_modality_from_text(
                    [
                        formula.get("operator"),
                        modality.get("force"),
                        modality.get("label"),
                    ]
                ),
                actor=actor,
                action=action,
                object=object_atom,
                conditions=_map_many(
                    formula.get("conditions") or (),
                    vocabulary.qualifiers,
                ),
                exceptions=_map_many(
                    formula.get("exceptions") or (),
                    vocabulary.qualifiers,
                ),
                temporal=_map_many(
                    structure.get("temporal_anchors") or (),
                    vocabulary.qualifiers,
                ),
            )
        )
    result = CanonicalRuleIR(tuple(rules))
    result.validate_vocabulary(vocabulary)
    return result


# More explicit public name while retaining the pilot function's terminology.
project_modal_spacy_record = project_decompiler_record


def _default_codec_factory(requested_model: str) -> object:
    from ipfs_datasets_py.logic.modal.codec import (
        DeterministicModalLogicCodec,
        ModalLogicCodecConfig,
    )

    return DeterministicModalLogicCodec(
        ModalLogicCodecConfig(
            parser_backend="spacy",
            spacy_model_name=requested_model,
        )
    )


def _default_repairer(modal_ir: object) -> Mapping[str, object]:
    from ipfs_datasets_py.logic.modal.decompiler_repairs import (
        repair_decompiler_round_trip,
    )

    result = repair_decompiler_round_trip(modal_ir)
    if not isinstance(result, Mapping):
        raise ContractError("modal decompiler repair returned a non-object")
    return result


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _frontend_diagnostics(
    codec: object | None,
    *,
    requested_model: str,
    required_pipeline: tuple[str, ...],
    required_model_version: str,
    encoded: object | None = None,
    status: ModalSpacyFrontendStatus | None = None,
    detail: str | None = None,
) -> ModalSpacyConstructorDiagnostics:
    encoder = getattr(codec, "encoder", None)
    encoding = getattr(encoded, "encoding", None)
    nlp = getattr(encoder, "nlp", None)
    codec_config = getattr(codec, "config", None)
    model_meta = _mapping(getattr(nlp, "meta", {}))
    effective_model = str(
        getattr(
            encoding,
            "model_name",
            getattr(encoder, "model_name", ""),
        )
        or ""
    )
    fallback_used = bool(
        getattr(
            encoding,
            "used_fallback_model",
            getattr(encoder, "used_fallback_model", False),
        )
    )
    effective_pipeline = tuple(
        str(item) for item in (getattr(nlp, "pipe_names", ()) or ())
    )
    model_version = str(model_meta.get("version", "") or "")
    language = str(
        getattr(nlp, "lang", model_meta.get("lang", "")) or ""
    )
    parser_backend = str(
        getattr(codec_config, "parser_backend", "") or ""
    )
    parser_name = str(getattr(encoded, "parser_name", "") or "")

    drift: list[str] = []
    if effective_model != requested_model:
        drift.append(
            f"effective model {effective_model!r} differs from "
            f"requested {requested_model!r}"
        )
    if fallback_used:
        drift.append("blank-model fallback was used")
    accepted_effective_pipelines = {
        required_pipeline,
        (*required_pipeline, *_CODEC_PIPELINE_ADDITIONS),
    }
    if effective_pipeline not in accepted_effective_pipelines:
        drift.append(
            "effective pipeline differs from the requested full pipeline"
        )
    if model_version != required_model_version:
        drift.append(
            f"effective model version {model_version!r} differs from "
            f"requested {required_model_version!r}"
        )
    if language != REQUIRED_SPACY_LANGUAGE:
        drift.append("effective spaCy language is not English")
    if parser_backend != "spacy":
        drift.append("modal codec parser backend is not spaCy")
    if encoded is not None and parser_name != SPACY_MODAL_PARSER:
        drift.append("effective modal parser is not the spaCy modal codec")

    if status is None:
        status = (
            ModalSpacyFrontendStatus.DEGRADED
            if drift
            else ModalSpacyFrontendStatus.FULL_MODEL
        )
    if detail is None and drift:
        detail = "; ".join(drift)
    return ModalSpacyConstructorDiagnostics(
        frontend_status=status,
        requested_model=requested_model,
        effective_model=effective_model,
        requested_pipeline=required_pipeline,
        effective_pipeline=effective_pipeline,
        requested_model_version=required_model_version,
        effective_model_version=model_version,
        language=language,
        fallback_used=fallback_used,
        parser_backend=parser_name or parser_backend,
        detail=detail,
    )


def _raw_formula_spans(modal_ir: object) -> dict[str, tuple[str, int, int]]:
    serialized = (
        modal_ir.to_dict()
        if callable(getattr(modal_ir, "to_dict", None))
        else modal_ir
    )
    document = _mapping(serialized)
    raw_formulas = document.get("formulas")
    if not isinstance(raw_formulas, Sequence) or isinstance(
        raw_formulas, (str, bytes, bytearray)
    ):
        return {}
    result: dict[str, tuple[str, int, int]] = {}
    for raw in raw_formulas:
        if not isinstance(raw, Mapping):
            continue
        formula_id = str(raw.get("formula_id") or "")
        provenance = _mapping(raw.get("provenance"))
        try:
            start = max(0, int(provenance.get("start_char") or 0))
            end = max(start, int(provenance.get("end_char") or 0))
        except (TypeError, ValueError):
            start, end = 0, 0
        result[formula_id] = (
            str(provenance.get("source_id") or ""),
            start,
            end,
        )
    return result


def _source_span_diagnostics(
    record: Mapping[str, object],
    modal_ir: object,
    source_text: str,
) -> tuple[SourceSpanDiagnostic, ...]:
    raw_spans = _raw_formula_spans(modal_ir)
    raw_formulas = record.get("formulas")
    if not isinstance(raw_formulas, Sequence) or isinstance(
        raw_formulas, (str, bytes, bytearray)
    ):
        return ()
    diagnostics: list[SourceSpanDiagnostic] = []
    for raw in raw_formulas:
        if not isinstance(raw, Mapping):
            continue
        formula_id = str(raw.get("formula_id") or "")
        source_id, start, end = raw_spans.get(
            formula_id, ("", 0, 0)
        )
        span_hash = str(raw.get("source_span_sha256") or "")
        if not span_hash and end > start:
            span = source_text[start : min(end, len(source_text))]
            if span:
                span_hash = hashlib.sha256(
                    span.encode("utf-8")
                ).hexdigest()
        diagnostics.append(
            SourceSpanDiagnostic(
                formula_id=formula_id,
                source_id=source_id,
                start_char=start,
                end_char=end,
                source_span_sha256=span_hash,
                structural_signature=str(
                    raw.get("structural_signature") or ""
                ),
            )
        )
    return tuple(
        sorted(
            diagnostics,
            key=lambda item: (
                item.start_char,
                item.end_char,
                item.formula_id,
            ),
        )
    )


def _failed(
    diagnostics: ModalSpacyConstructorDiagnostics,
    reason: FailureReason,
    detail: str,
) -> ModalSpacyConstruction:
    return ModalSpacyConstruction(
        result=ConstructorResult(
            ComponentStatus.FAILED,
            failure_reason=reason,
            failure_detail=detail,
        ),
        diagnostics=replace(diagnostics, detail=detail),
    )


def _request_config_error(
    request: ConstructorRequest,
    *,
    requested_model: str,
    required_pipeline: tuple[str, ...],
) -> str | None:
    config = request.config
    for field in ("requested_model", "spacy_model_name"):
        if field in config and config[field] != requested_model:
            return (
                f"constructor config {field} must equal the pinned "
                f"model {requested_model!r}"
            )
    if "parser_backend" in config and config["parser_backend"] != "spacy":
        return "constructor config cannot replace the spaCy parser backend"
    for field in ("allow_fallback", "fallback_allowed"):
        if config.get(field) is True:
            return "constructor config cannot enable spaCy fallback"
    if "required_pipeline" in config:
        configured = config["required_pipeline"]
        if (
            not isinstance(configured, Sequence)
            or isinstance(configured, (str, bytes, bytearray))
            or tuple(configured) != required_pipeline
        ):
            return "constructor config cannot weaken the full spaCy pipeline"
    return None


class ModalSpacyCanonicalConstructor:
    """Adapter from the production modal/full-spaCy route to canonical IR."""

    identity: Final = MODAL_SPACY_CANONICAL_CONSTRUCTOR_INTERFACE

    def __init__(
        self,
        *,
        requested_model: str = DEFAULT_SPACY_MODEL,
        required_pipeline: Sequence[str] = REQUIRED_SPACY_PIPELINE,
        required_model_version: str = DEFAULT_SPACY_MODEL_VERSION,
        codec_factory: Callable[[str], object] | None = None,
        repairer: Callable[[object], Mapping[str, object]] | None = None,
    ) -> None:
        if not isinstance(requested_model, str) or not requested_model.strip():
            raise ContractError("requested_model must be nonblank")
        pipeline = tuple(required_pipeline)
        if not pipeline or not all(
            isinstance(item, str) and item for item in pipeline
        ):
            raise ContractError(
                "required_pipeline must be a nonempty string sequence"
            )
        if (
            not isinstance(required_model_version, str)
            or not required_model_version.strip()
        ):
            raise ContractError("required_model_version must be nonblank")
        if codec_factory is not None and not callable(codec_factory):
            raise ContractError("codec_factory must be callable")
        if repairer is not None and not callable(repairer):
            raise ContractError("repairer must be callable")
        self.requested_model = requested_model
        self.required_pipeline = pipeline
        self.required_model_version = required_model_version
        self._codec_factory = codec_factory or _default_codec_factory
        self._repairer = repairer or _default_repairer

    def construct_with_diagnostics(
        self, request: ConstructorRequest
    ) -> ModalSpacyConstruction:
        """Construct canonical IR and retain diagnostics on a separate path."""

        empty_diagnostics = _frontend_diagnostics(
            None,
            requested_model=self.requested_model,
            required_pipeline=self.required_pipeline,
            required_model_version=self.required_model_version,
            status=ModalSpacyFrontendStatus.UNAVAILABLE,
            detail="full spaCy frontend has not been initialized",
        )
        if not isinstance(request, ConstructorRequest):
            return _failed(
                empty_diagnostics,
                FailureReason.INVALID_OUTPUT,
                "request must be ConstructorRequest",
            )
        config_error = _request_config_error(
            request,
            requested_model=self.requested_model,
            required_pipeline=self.required_pipeline,
        )
        if config_error:
            return _failed(
                empty_diagnostics,
                FailureReason.INVALID_OUTPUT,
                config_error,
            )

        try:
            codec = self._codec_factory(self.requested_model)
        except (
            ImportError,
            ModuleNotFoundError,
            PermissionError,
            RuntimeError,
        ) as exc:
            return _failed(
                empty_diagnostics,
                FailureReason.CAPABILITY_UNAVAILABLE,
                "full spaCy frontend unavailable while loading "
                f"{self.requested_model!r}: {type(exc).__name__}",
            )
        except Exception as exc:
            return _failed(
                empty_diagnostics,
                FailureReason.EXCEPTION,
                "modal spaCy codec factory raised "
                f"{type(exc).__name__}",
            )

        diagnostics = _frontend_diagnostics(
            codec,
            requested_model=self.requested_model,
            required_pipeline=self.required_pipeline,
            required_model_version=self.required_model_version,
        )
        if (
            diagnostics.frontend_status
            is not ModalSpacyFrontendStatus.FULL_MODEL
        ):
            return _failed(
                diagnostics,
                FailureReason.CAPABILITY_UNAVAILABLE,
                "full spaCy frontend degraded: "
                f"{diagnostics.detail or 'identity mismatch'}",
            )

        document_id = request.config.get("document_id")
        citation = request.config.get("citation")
        source = request.config.get(
            "source", "semantic_roundtrip_modal_spacy_constructor"
        )
        if document_id is not None and not isinstance(document_id, str):
            return _failed(
                diagnostics,
                FailureReason.INVALID_OUTPUT,
                "constructor config document_id must be a string",
            )
        if citation is not None and not isinstance(citation, str):
            return _failed(
                diagnostics,
                FailureReason.INVALID_OUTPUT,
                "constructor config citation must be a string",
            )
        if not isinstance(source, str) or not source.strip():
            return _failed(
                diagnostics,
                FailureReason.INVALID_OUTPUT,
                "constructor config source must be a nonblank string",
            )

        try:
            encoded = codec.encode(
                request.source_text,
                document_id=document_id,
                citation=citation,
                source=source,
            )
        except (
            ImportError,
            ModuleNotFoundError,
            PermissionError,
            RuntimeError,
        ) as exc:
            unavailable = replace(
                diagnostics,
                frontend_status=ModalSpacyFrontendStatus.UNAVAILABLE,
            )
            return _failed(
                unavailable,
                FailureReason.CAPABILITY_UNAVAILABLE,
                "full spaCy frontend unavailable during encoding: "
                f"{type(exc).__name__}",
            )
        except Exception as exc:
            unavailable = replace(
                diagnostics,
                frontend_status=ModalSpacyFrontendStatus.UNAVAILABLE,
            )
            return _failed(
                unavailable,
                FailureReason.EXCEPTION,
                "modal spaCy codec raised "
                f"{type(exc).__name__}",
            )

        diagnostics = _frontend_diagnostics(
            codec,
            requested_model=self.requested_model,
            required_pipeline=self.required_pipeline,
            required_model_version=self.required_model_version,
            encoded=encoded,
        )
        if (
            diagnostics.frontend_status
            is not ModalSpacyFrontendStatus.FULL_MODEL
        ):
            return _failed(
                diagnostics,
                FailureReason.CAPABILITY_UNAVAILABLE,
                "full spaCy frontend degraded: "
                f"{diagnostics.detail or 'identity mismatch'}",
            )

        modal_ir = getattr(encoded, "modal_ir", None)
        if modal_ir is None:
            return _failed(
                diagnostics,
                FailureReason.MISSING_OUTPUT,
                "modal spaCy codec returned no modal IR",
            )
        try:
            record = self._repairer(modal_ir)
            if not isinstance(record, Mapping):
                raise ContractError(
                    "modal decompiler repair returned a non-object"
                )
            source_spans = _source_span_diagnostics(
                record, modal_ir, request.source_text
            )
            diagnostics = replace(
                diagnostics, source_spans=source_spans
            )
            canonical_ir = project_decompiler_record(
                record, request.allowed_atom_vocabulary
            )
        except ContractError as exc:
            return _failed(
                diagnostics,
                FailureReason.INVALID_OUTPUT,
                f"modal spaCy projection rejected: {exc}",
            )
        except (AttributeError, TypeError, ValueError) as exc:
            return _failed(
                diagnostics,
                FailureReason.INVALID_OUTPUT,
                "modal spaCy projection rejected: "
                f"{type(exc).__name__}",
            )
        except Exception as exc:
            return _failed(
                diagnostics,
                FailureReason.EXCEPTION,
                "modal spaCy projection raised "
                f"{type(exc).__name__}",
            )

        if canonical_ir.is_empty:
            return _failed(
                diagnostics,
                FailureReason.EMPTY_L1,
                "modal spaCy projection produced empty canonical L1",
            )
        return ModalSpacyConstruction(
            result=ConstructorResult(
                ComponentStatus.SUCCESS,
                canonical_ir=canonical_ir,
            ),
            diagnostics=diagnostics,
        )

    def construct(self, request: ConstructorRequest) -> ConstructorResult:
        """Return only the protocol result; diagnostics remain out of-band."""

        return self.construct_with_diagnostics(request).result


# Concise compatibility alias for callers that omit "Canonical".
ModalSpacyConstructor = ModalSpacyCanonicalConstructor


assert isinstance(ModalSpacyCanonicalConstructor(), RoundTripConstructor)


__all__ = [
    "DEFAULT_SPACY_MODEL",
    "DEFAULT_SPACY_MODEL_VERSION",
    "MODAL_SPACY_CANONICAL_CONSTRUCTOR_INTERFACE",
    "ModalSpacyCanonicalConstructor",
    "ModalSpacyConstruction",
    "ModalSpacyConstructor",
    "ModalSpacyConstructorDiagnostics",
    "ModalSpacyFrontendStatus",
    "REQUIRED_SPACY_PIPELINE",
    "SourceSpanDiagnostic",
    "project_decompiler_record",
    "project_modal_spacy_record",
]
