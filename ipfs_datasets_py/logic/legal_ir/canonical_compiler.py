"""Measured deterministic compiler for the canonical legal round-trip IR.

The implementation is a production adapter around :class:`DeonticConverter`.
It deliberately repeats the small, reviewed projection used by
``TypedDeonticCanonicalConstructor@1`` instead of importing the un-packaged
benchmark package.  Its atom vocabulary is always supplied by the caller; no
fixture vocabulary, model, repair route, or inferred fallback is available.

The result boundary is fail closed:

* component unavailability and exceptions are typed failures;
* no parser output is a typed empty-output failure;
* semantics outside the measured deontic/vocabulary projection cause an
  abstention unless the request explicitly permits a disclosed partial IR;
* every successful result binds its IR, source map, measured adapter,
  configuration, and selected benchmark arm with CIDv1 receipts.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
    CANONICAL_STRUCTURED_TEXT_COMPILER_INTERFACE,
    IMPLEMENTATION_REPRESENTATIVE_ARM_ID,
    IMPLEMENTATION_REPRESENTATIVE_ARM_IDENTITY_CID,
    SELECTED_CONSTRUCTOR_ADAPTER_RAW_CID,
    SELECTED_CONSTRUCTOR_INTERFACE,
    SELECTION_BASIS,
    CanonicalAtomVocabulary,
    CanonicalContractError,
    CanonicalDiagnostic,
    CanonicalError,
    CanonicalErrorCode,
    CanonicalRoundTripIR,
    CanonicalRule,
    CanonicalStructuredTextCompiler,
    CompilerRequest,
    CompilerResult,
    ComponentTrace,
    DiagnosticSeverity,
    OperationStatus,
    SourceMapEntry,
    UnsupportedDisposition,
    UnsupportedSemantic,
)
from ipfs_datasets_py.utils.cid_utils import cid_for_dag_json

# Residual LIG-003 CID hygiene: deliberate pin of the current measured
# typed-deontic adapter module bytes
# (``benchmarks/semantic_roundtrip/constructors/typed_deontic.py``).
#
# The replacement-gate selection identity
# (:data:`SELECTED_CONSTRUCTOR_ADAPTER_RAW_CID`) remains the historical
# evidence-bound raw CID from the frozen selection report.  The on-disk
# research adapter later evolved under EVAL-005 and the PLAT/PLAT2
# deterministic edit waves.  Production remains bound to the selected
# historical behavior, while drift in the evolving research adapter stays
# visible.  Production integrity therefore pins *both*:
#
# * selection lineage → ``SELECTED_CONSTRUCTOR_ADAPTER_RAW_CID``
# * current measured adapter bytes → ``MEASURED_TYPED_DEONTIC_ADAPTER_RAW_CID``
#
# Any intentional adapter edit requires a deliberate update of this constant
# and revalidation of the frozen L1 suite.  Do not weaken the exact-CID check.
MEASURED_TYPED_DEONTIC_ADAPTER_RAW_CID: Final = (
    "bafkreife5avbe5esju4frufsogvzlaew5x5qw5h4qlefvgx2qdbamqsyny"
)
"""CIDv1/raw of the current measured typed-deontic adapter module bytes."""


def _compiler_configuration_payload() -> dict[str, object]:
    """Build a detached strict-JSON form of the measured configuration."""

    return {
        "interface": CANONICAL_STRUCTURED_TEXT_COMPILER_INTERFACE,
        "constructor": {
            "interface": SELECTED_CONSTRUCTOR_INTERFACE,
            # Historical replacement-gate selection identity (shared contracts).
            "adapter_raw_cid": SELECTED_CONSTRUCTOR_ADAPTER_RAW_CID,
        },
        "selection": {
            "arm_id": IMPLEMENTATION_REPRESENTATIVE_ARM_ID,
            "arm_identity_cid": IMPLEMENTATION_REPRESENTATIVE_ARM_IDENTITY_CID,
            "basis": SELECTION_BASIS,
        },
        "composition": {
            "base_constructor_id": "typed_deontic",
            "guidance": "no_guidance",
            "repair": "no_repair",
            "constructor_route": "not_applicable",
        },
        "converter": {
            "use_cache": False,
            "use_ipfs": False,
            "use_ml": False,
            "enable_monitoring": False,
            "document_type": "general",
        },
        "fallback_allowed": False,
        "learned_stages": [],
    }


_CONFIG_PAYLOAD = _compiler_configuration_payload()
TYPED_DEONTIC_COMPILER_CONFIG: Final[Mapping[str, object]] = MappingProxyType(
    {
        "interface": _CONFIG_PAYLOAD["interface"],
        "constructor": MappingProxyType(
            dict(_CONFIG_PAYLOAD["constructor"])  # type: ignore[arg-type]
        ),
        "selection": MappingProxyType(
            dict(_CONFIG_PAYLOAD["selection"])  # type: ignore[arg-type]
        ),
        "composition": MappingProxyType(
            dict(_CONFIG_PAYLOAD["composition"])  # type: ignore[arg-type]
        ),
        "converter": MappingProxyType(
            dict(_CONFIG_PAYLOAD["converter"])  # type: ignore[arg-type]
        ),
        "fallback_allowed": False,
        "learned_stages": (),
    }
)
"""Recursively immutable view of the exact measured production profile."""

TYPED_DEONTIC_COMPILER_CONFIG_CID: Final = cid_for_dag_json(_CONFIG_PAYLOAD)
"""DAG-JSON CID of the detached measured configuration payload."""
del _CONFIG_PAYLOAD

_TOKEN_RE: Final = re.compile(r"[a-z0-9]+")
_ALLOWED_REQUEST_CONFIG: Final = frozenset({"document_type"})
_SUPPORTED_NORM_TYPES: Final = frozenset(
    {"", "obligation", "duty", "permission", "prohibition"}
)
_UNREPRESENTED_SEMANTIC_FIELDS: Final = (
    "mental_state",
    "recipient",
    "overrides",
    "cross_references",
    "resolved_cross_references",
    "defined_terms",
    "penalty",
    "procedure",
    "definition_scope",
)
_RULE_FIELDS: Final = (
    "modality",
    "actor",
    "action",
    "object",
    "conditions",
    "exceptions",
    "temporal",
)


def compiler_configuration() -> dict[str, object]:
    """Return a detached JSON copy of the frozen measured configuration."""

    return _compiler_configuration_payload()


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
    """Apply the measured deterministic atom projection without inference."""

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


def _many_values(value: object) -> list[object]:
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return list(value)
    if value is None or value == "" or value == []:
        return []
    return [value]


def _has_semantic_value(value: object) -> bool:
    if value is None or value is False or value == "":
        return False
    if isinstance(value, (Mapping, Sequence)) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return bool(value)
    return True


def _unmapped_qualifier_count(
    value: object,
    candidates: Sequence[str],
) -> int:
    return sum(
        1
        for item in _many_values(value)
        if _clean_text(" ".join(_flatten_strings(item)))
        and not _best_atom(item, candidates)
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


def _norm_data(norm: object) -> Mapping[str, object]:
    to_dict = getattr(norm, "to_dict", None)
    if not callable(to_dict):
        raise CanonicalContractError(
            "typed deontic norm must provide to_dict()"
        )
    data = to_dict()
    if not isinstance(data, Mapping):
        raise CanonicalContractError(
            "typed deontic norm to_dict() must return an object"
        )
    return data


def _rule_sort_key(rule: CanonicalRule) -> tuple[object, ...]:
    return (
        rule.modality,
        rule.actor,
        rule.action,
        rule.object,
        rule.conditions,
        rule.exceptions,
        rule.temporal,
        rule.rule_cid,
    )


@dataclass(frozen=True, slots=True)
class _ProjectedRule:
    rule: CanonicalRule
    norm: object
    norm_index: int


@dataclass(frozen=True, slots=True)
class _UnsupportedProjection:
    code: str
    message: str
    norm: object
    norm_index: int


def _project_legal_norms(
    norms: Sequence[object],
    vocabulary: CanonicalAtomVocabulary,
) -> tuple[tuple[_ProjectedRule, ...], tuple[_UnsupportedProjection, ...]]:
    if not isinstance(vocabulary, CanonicalAtomVocabulary):
        raise CanonicalContractError(
            "vocabulary must be CanonicalAtomVocabulary"
        )
    if not isinstance(norms, Sequence) or isinstance(
        norms, (str, bytes, bytearray)
    ):
        raise CanonicalContractError("norms must be an array")

    projected: list[_ProjectedRule] = []
    unsupported: list[_UnsupportedProjection] = []
    for norm_index, norm in enumerate(norms):
        data = _norm_data(norm)
        for field_name in _UNREPRESENTED_SEMANTIC_FIELDS:
            if not _has_semantic_value(data.get(field_name)):
                continue
            unsupported.append(
                _UnsupportedProjection(
                    code=f"typed_deontic.unrepresented_{field_name}",
                    message=(
                        f"The typed deontic {field_name} facet is nonempty "
                        "but CanonicalRoundTripIR@1 has no reviewed field for "
                        "it."
                    ),
                    norm=norm,
                    norm_index=norm_index,
                )
            )

        norm_type = _clean_text(data.get("norm_type")).lower()
        if norm_type not in _SUPPORTED_NORM_TYPES:
            unsupported.append(
                _UnsupportedProjection(
                    code="typed_deontic.unsupported_norm_type",
                    message=(
                        "The typed deontic record has semantics outside the "
                        "measured O/P/F canonical grammar."
                    ),
                    norm=norm,
                    norm_index=norm_index,
                )
            )
            continue

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
            missing = [
                field
                for field, value in (("actor", actor), ("action", action))
                if not value
            ]
            unsupported.append(
                _UnsupportedProjection(
                    code="typed_deontic.unmapped_required_atom",
                    message=(
                        "The typed deontic record could not map required "
                        f"{', '.join(missing)} fields into the caller-supplied "
                        "vocabulary."
                    ),
                    norm=norm,
                    norm_index=norm_index,
                )
            )
            continue

        if (
            _clean_text(" ".join(_flatten_strings(data.get("action_object"))))
            and not object_atom
        ):
            unsupported.append(
                _UnsupportedProjection(
                    code="typed_deontic.unmapped_object",
                    message=(
                        "The typed deontic object could not map into the "
                        "caller-supplied object vocabulary."
                    ),
                    norm=norm,
                    norm_index=norm_index,
                )
            )

        qualifier_inputs = {
            "condition": data.get("conditions") or (),
            "exception": data.get("exceptions") or (),
            "temporal": data.get("temporal_constraints") or (),
        }
        for facet, values in qualifier_inputs.items():
            unmapped_count = _unmapped_qualifier_count(
                values,
                vocabulary.qualifiers,
            )
            if not unmapped_count:
                continue
            unsupported.append(
                _UnsupportedProjection(
                    code=f"typed_deontic.unmapped_{facet}",
                    message=(
                        f"{unmapped_count} typed deontic {facet} value(s) "
                        "could not map into the caller-supplied qualifier "
                        "vocabulary."
                    ),
                    norm=norm,
                    norm_index=norm_index,
                )
            )

        projected.append(
            _ProjectedRule(
                rule=CanonicalRule(
                    modality=_modality_from_text(
                        [data.get("modality"), data.get("norm_type")]
                    ),
                    actor=actor,
                    action=action,
                    object=object_atom,
                    conditions=_map_many(
                        data.get("conditions") or (),
                        vocabulary.qualifiers,
                    ),
                    exceptions=_map_many(
                        data.get("exceptions") or (),
                        vocabulary.qualifiers,
                    ),
                    temporal=_map_many(
                        data.get("temporal_constraints") or (),
                        vocabulary.qualifiers,
                    ),
                ),
                norm=norm,
                norm_index=norm_index,
            )
        )

    return (
        tuple(sorted(projected, key=lambda item: _rule_sort_key(item.rule))),
        tuple(unsupported),
    )


def project_legal_norms(
    norms: Sequence[object],
    vocabulary: CanonicalAtomVocabulary,
) -> CanonicalRoundTripIR:
    """Project supported ``LegalNormIR`` objects into measured canonical IR.

    This low-level parity helper raises when no supported rule exists.  The
    production :meth:`TypedDeonticCanonicalCompiler.compile` method converts
    that condition and any unsupported records into typed terminal results.
    """

    projected, unsupported = _project_legal_norms(norms, vocabulary)
    if unsupported:
        raise CanonicalContractError(
            "typed deontic projection contains unsupported semantics; use "
            "TypedDeonticCanonicalCompiler for a typed abstention or explicit "
            "partial result"
        )
    if not projected:
        raise CanonicalContractError(
            "typed deontic records did not map to supported canonical rules"
        )
    return CanonicalRoundTripIR(tuple(item.rule for item in projected))


def _span_for_norm(norm: object, source_text: str) -> tuple[int, int]:
    """Return one valid global source span for a typed deontic record."""

    span = getattr(norm, "source_span", None)
    start = getattr(span, "start", None)
    end = getattr(span, "end", None)
    if (
        isinstance(start, int)
        and not isinstance(start, bool)
        and isinstance(end, int)
        and not isinstance(end, bool)
        and 0 <= start < end <= len(source_text)
    ):
        return start, end

    for name in ("source_text", "support_text"):
        excerpt = getattr(norm, name, None)
        if not isinstance(excerpt, str) or not excerpt:
            continue
        found = source_text.find(excerpt)
        if found >= 0:
            return found, found + len(excerpt)
    return 0, len(source_text)


def _source_map(
    projected: Sequence[_ProjectedRule],
    request: CompilerRequest,
) -> tuple[SourceMapEntry, ...]:
    entries: list[SourceMapEntry] = []
    for rule_index, item in enumerate(projected):
        start, end = _span_for_norm(item.norm, request.source_text)
        for field_name in _RULE_FIELDS:
            entries.append(
                SourceMapEntry(
                    rule_cid=item.rule.rule_cid,
                    field_path=f"/rules/{rule_index}/{field_name}",
                    source_cid=request.source_cid,
                    start=start,
                    end=end,
                    attribution="coarse:typed_deontic_record_span",
                )
            )
    return tuple(entries)


def _unsupported_semantics(
    records: Sequence[_UnsupportedProjection],
    request: CompilerRequest,
    *,
    partial: bool,
) -> tuple[UnsupportedSemantic, ...]:
    disposition = (
        UnsupportedDisposition.EXPLICIT_PARTIAL
        if partial
        else UnsupportedDisposition.ABSTAIN
    )
    return tuple(
        UnsupportedSemantic(
            code=record.code,
            message=record.message,
            disposition=disposition,
            source_cid=request.source_cid,
            start=_span_for_norm(record.norm, request.source_text)[0],
            end=_span_for_norm(record.norm, request.source_text)[1],
        )
        for record in records
    )


def _base_provenance(
    request: CompilerRequest,
    *,
    terminal_stage: str,
) -> dict[str, object]:
    body: dict[str, object] = {
        "interface": CANONICAL_STRUCTURED_TEXT_COMPILER_INTERFACE,
        "request_cid": request.request_cid,
        "source_cid": request.source_cid,
        "policy_cid": request.policy_cid,
        "constructor_interface": SELECTED_CONSTRUCTOR_INTERFACE,
        "constructor_adapter_raw_cid": SELECTED_CONSTRUCTOR_ADAPTER_RAW_CID,
        # Deliberate residual hygiene pin of current on-disk adapter bytes
        # (distinct from the historical selection identity above).
        "measured_adapter_raw_cid": MEASURED_TYPED_DEONTIC_ADAPTER_RAW_CID,
        "implementation_representative_arm_id": (
            IMPLEMENTATION_REPRESENTATIVE_ARM_ID
        ),
        "implementation_representative_arm_identity_cid": (
            IMPLEMENTATION_REPRESENTATIVE_ARM_IDENTITY_CID
        ),
        "selection_basis": SELECTION_BASIS,
        "compiler_config_cid": TYPED_DEONTIC_COMPILER_CONFIG_CID,
        "terminal_stage": terminal_stage,
        "deterministic": True,
        "fallback_allowed": False,
        "fallback_used": False,
        "learned_stages": [],
        "model_call_count": 0,
    }
    return {**body, "provenance_cid": cid_for_dag_json(body)}


def _diagnostic(
    code: str,
    message: str,
    severity: DiagnosticSeverity,
    request: CompilerRequest,
    span: tuple[int, int] | None = None,
) -> CanonicalDiagnostic:
    if span is None:
        return CanonicalDiagnostic(code, message, severity)
    return CanonicalDiagnostic(
        code,
        message,
        severity,
        source_cid=request.source_cid,
        start=span[0],
        end=span[1],
    )


def _failure(
    request: CompilerRequest,
    *,
    code: CanonicalErrorCode,
    message: str,
    terminal_stage: str,
    retryable: bool = False,
    details: Mapping[str, object] | None = None,
    diagnostics: Sequence[CanonicalDiagnostic] = (),
    unsupported: Sequence[UnsupportedSemantic] = (),
    abstained: bool = False,
) -> CompilerResult:
    return CompilerResult(
        status=(
            OperationStatus.ABSTAINED
            if abstained
            else OperationStatus.FAILED
        ),
        request_cid=request.request_cid,
        unsupported_semantics=tuple(unsupported),
        provenance=_base_provenance(
            request,
            terminal_stage=terminal_stage,
        ),
        diagnostics=tuple(diagnostics),
        error=CanonicalError(
            code=code,
            message=message,
            retryable=retryable,
            details={} if details is None else details,
        ),
    )


def _request_config_error(request: CompilerRequest) -> str | None:
    config = dict(request.config)
    unknown = sorted(set(config) - _ALLOWED_REQUEST_CONFIG)
    if unknown:
        return (
            "The measured compiler accepts no optional stages or overrides; "
            f"unsupported config keys: {', '.join(unknown)}."
        )
    if config.get("document_type", "general") != "general":
        return (
            "The measured compiler requires document_type='general'; "
            "changing it would select an unmeasured parser configuration."
        )
    return None


def _load_deontic_components() -> tuple[type[object], type[object]]:
    """Load the optional production parser lazily at the execution boundary."""

    from ipfs_datasets_py.logic.deontic.converter import DeonticConverter
    from ipfs_datasets_py.logic.deontic.ir import LegalNormIR

    return DeonticConverter, LegalNormIR


class TypedDeonticCanonicalCompiler:
    """Production implementation of ``CanonicalStructuredTextCompiler@1``."""

    @property
    def identity(self) -> str:
        return CANONICAL_STRUCTURED_TEXT_COMPILER_INTERFACE

    @property
    def configuration_cid(self) -> str:
        return TYPED_DEONTIC_COMPILER_CONFIG_CID

    def compile(self, request: CompilerRequest) -> CompilerResult:
        if not isinstance(request, CompilerRequest):
            raise CanonicalContractError(
                "request must be CompilerRequest; unbound input is rejected"
            )

        config_error = _request_config_error(request)
        if config_error is not None:
            return _failure(
                request,
                code=CanonicalErrorCode.INVALID_REQUEST,
                message=config_error,
                terminal_stage="request_validation",
                diagnostics=(
                    _diagnostic(
                        "compiler.unmeasured_configuration",
                        config_error,
                        DiagnosticSeverity.ERROR,
                        request,
                    ),
                ),
            )

        try:
            converter_type, legal_norm_type = _load_deontic_components()
        except ImportError:
            message = "The selected typed deontic component is unavailable."
            return _failure(
                request,
                code=CanonicalErrorCode.COMPONENT_UNAVAILABLE,
                message=message,
                terminal_stage="component_loading",
                retryable=True,
                diagnostics=(
                    _diagnostic(
                        "compiler.component_unavailable",
                        message,
                        DiagnosticSeverity.ERROR,
                        request,
                    ),
                ),
            )
        except Exception as exc:
            message = (
                "The selected typed deontic component could not be loaded "
                f"because initialization raised {type(exc).__name__}; no "
                "fallback was attempted."
            )
            return _failure(
                request,
                code=CanonicalErrorCode.COMPONENT_FAILED,
                message=message,
                terminal_stage="component_loading",
                details={"exception_type": type(exc).__name__},
                diagnostics=(
                    _diagnostic(
                        "compiler.component_load_failed",
                        message,
                        DiagnosticSeverity.ERROR,
                        request,
                    ),
                ),
            )

        try:
            converter = converter_type(
                use_cache=False,
                use_ipfs=False,
                use_ml=False,
                enable_monitoring=False,
                document_type="general",
            )
            converted = converter.convert(request.source_text, use_cache=False)
        except Exception as exc:
            message = (
                "The selected typed deontic component raised "
                f"{type(exc).__name__}; no fallback was attempted."
            )
            return _failure(
                request,
                code=CanonicalErrorCode.COMPONENT_FAILED,
                message=message,
                terminal_stage="typed_deontic_conversion",
                details={"exception_type": type(exc).__name__},
                diagnostics=(
                    _diagnostic(
                        "compiler.component_failed",
                        message,
                        DiagnosticSeverity.ERROR,
                        request,
                    ),
                ),
            )

        output = getattr(converted, "output", None)
        if output is None:
            message = "The selected typed deontic component returned no output."
            return _failure(
                request,
                code=CanonicalErrorCode.EMPTY_OUTPUT,
                message=message,
                terminal_stage="typed_deontic_conversion",
                diagnostics=(
                    _diagnostic(
                        "compiler.empty_component_output",
                        message,
                        DiagnosticSeverity.ERROR,
                        request,
                    ),
                ),
            )

        elements = list(getattr(output, "parser_elements", ()) or ())
        if not elements:
            message = (
                "The selected typed deontic component returned no parser "
                "elements; arbitrary text was not coerced into an obligation."
            )
            return _failure(
                request,
                code=CanonicalErrorCode.EMPTY_OUTPUT,
                message=message,
                terminal_stage="typed_deontic_conversion",
                diagnostics=(
                    _diagnostic(
                        "compiler.empty_l1",
                        message,
                        DiagnosticSeverity.ERROR,
                        request,
                    ),
                ),
            )

        try:
            norms = [
                legal_norm_type.from_parser_element(element)
                for element in elements
            ]
            projected, unsupported_records = _project_legal_norms(
                norms,
                request.atom_vocabulary,
            )
        except Exception as exc:
            message = (
                "The selected typed deontic projection raised "
                f"{type(exc).__name__}; no fallback was attempted."
            )
            return _failure(
                request,
                code=CanonicalErrorCode.COMPONENT_FAILED,
                message=message,
                terminal_stage="canonical_projection",
                details={"exception_type": type(exc).__name__},
                diagnostics=(
                    _diagnostic(
                        "compiler.projection_failed",
                        message,
                        DiagnosticSeverity.ERROR,
                        request,
                    ),
                ),
            )

        if unsupported_records and (
            not request.allow_explicit_partial or not projected
        ):
            unsupported = _unsupported_semantics(
                unsupported_records,
                request,
                partial=False,
            )
            affected_norm_count = len(
                {record.norm_index for record in unsupported_records}
            )
            message = (
                f"{len(unsupported)} unsupported semantic issue(s) affect "
                f"{affected_norm_count} typed deontic record(s); the compiler "
                "abstained."
            )
            return _failure(
                request,
                code=CanonicalErrorCode.UNSUPPORTED_SEMANTICS,
                message=message,
                terminal_stage="canonical_projection",
                details={
                    "unsupported_semantic_count": len(unsupported),
                    "affected_norm_count": affected_norm_count,
                },
                diagnostics=tuple(
                    _diagnostic(
                        item.code,
                        item.message,
                        DiagnosticSeverity.ERROR,
                        request,
                        (item.start, item.end),
                    )
                    for item in unsupported
                ),
                unsupported=unsupported,
                abstained=True,
            )

        if not projected:
            message = (
                "Typed deontic records did not map to a nonempty canonical IR."
            )
            return _failure(
                request,
                code=CanonicalErrorCode.EMPTY_OUTPUT,
                message=message,
                terminal_stage="canonical_projection",
                diagnostics=(
                    _diagnostic(
                        "compiler.empty_l1",
                        message,
                        DiagnosticSeverity.ERROR,
                        request,
                    ),
                ),
            )

        try:
            canonical_ir = CanonicalRoundTripIR(
                tuple(item.rule for item in projected)
            )
        except CanonicalContractError as exc:
            message = (
                "The projected rules violate CanonicalRoundTripIR@1: "
                f"{exc}"
            )
            return _failure(
                request,
                code=CanonicalErrorCode.INVALID_IR,
                message=message,
                terminal_stage="canonical_ir_validation",
                diagnostics=(
                    _diagnostic(
                        "compiler.invalid_ir",
                        message,
                        DiagnosticSeverity.ERROR,
                        request,
                    ),
                ),
            )
        partial_unsupported = _unsupported_semantics(
            unsupported_records,
            request,
            partial=True,
        )
        diagnostics: list[CanonicalDiagnostic] = [
            _diagnostic(
                "compiler.measured_path",
                (
                    "The measured deterministic typed-deontic path completed "
                    "without guidance, repair, model use, or fallback."
                ),
                DiagnosticSeverity.INFO,
                request,
            )
        ]
        diagnostics.extend(
            _diagnostic(
                item.code,
                item.message,
                DiagnosticSeverity.WARNING,
                request,
                (item.start, item.end),
            )
            for item in partial_unsupported
        )
        trace = ComponentTrace(
            component_id=IMPLEMENTATION_REPRESENTATIVE_ARM_ID,
            component_interface=SELECTED_CONSTRUCTOR_INTERFACE,
            input_cid=request.request_cid,
            input_codec="dag-json",
            output_cid=canonical_ir.ir_cid,
            output_codec="dag-json",
            config_cid=TYPED_DEONTIC_COMPILER_CONFIG_CID,
            deterministic=True,
        )
        return CompilerResult(
            status=OperationStatus.SUCCESS,
            request_cid=request.request_cid,
            canonical_ir=canonical_ir,
            source_map=_source_map(projected, request),
            unsupported_semantics=partial_unsupported,
            provenance=_base_provenance(
                request,
                terminal_stage="complete",
            ),
            diagnostics=tuple(diagnostics),
            component_trace=(trace,),
        )


# The short alias is convenient for callers while the descriptive class name
# keeps the selected implementation visible in traces and documentation.
CanonicalCompiler = TypedDeonticCanonicalCompiler

assert isinstance(TypedDeonticCanonicalCompiler(), CanonicalStructuredTextCompiler)


__all__ = [
    "CanonicalCompiler",
    "MEASURED_TYPED_DEONTIC_ADAPTER_RAW_CID",
    "TYPED_DEONTIC_COMPILER_CONFIG",
    "TYPED_DEONTIC_COMPILER_CONFIG_CID",
    "TypedDeonticCanonicalCompiler",
    "compiler_configuration",
    "project_legal_norms",
]
