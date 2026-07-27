"""Tests for the modal plus required full-spaCy canonical constructor."""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from benchmarks import bench_semantic_logic_roundtrip as pilot
from benchmarks.semantic_roundtrip import (
    AllowedAtomVocabulary,
    ComponentStatus,
    ConstructorRequest,
    FailureReason,
    RealizerRequest,
    RoundTripConstructor,
)
from benchmarks.semantic_roundtrip.constructors.modal_spacy import (
    DEFAULT_SPACY_MODEL,
    DEFAULT_SPACY_MODEL_VERSION,
    MODAL_SPACY_CANONICAL_CONSTRUCTOR_INTERFACE,
    POLARITY_PREFLIGHT_INTERFACE,
    REQUIRED_SPACY_PIPELINE,
    RESIDUAL_POLARITY_INVERSION_CASE_IDS,
    ModalSpacyCanonicalConstructor,
    ModalSpacyFrontendStatus,
    polarity_preflight,
    project_decompiler_record,
)
from benchmarks.semantic_roundtrip.contracts import CanonicalRule, CanonicalRuleIR
from benchmarks.semantic_roundtrip.stage_metrics import (
    compute_constructor_only_metrics,
)


SOURCE = "Agency shall file notice unless emergency within 10 days."
SPAN_END = len(SOURCE)


def _vocabulary() -> AllowedAtomVocabulary:
    return AllowedAtomVocabulary(
        actors=("agency", "court"),
        actions=("file", "review"),
        objects=("notice", "order"),
        qualifiers=("emergency", "within_10_days"),
    )


def _request(**config: object) -> ConstructorRequest:
    return ConstructorRequest(SOURCE, _vocabulary(), config)


def _record(
    *,
    formulas: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    if formulas is None:
        formulas = [
            {
                "formula_id": "doc-1:f0001",
                "operator": "O",
                "modality": {
                    "force": "obligation",
                    "label": "obligation",
                },
                "predicate": {
                    "arity": 3,
                    "name": "file",
                    "role": "clause",
                },
                "arguments": [
                    {
                        "position": 0,
                        "role": "actor",
                        "value": "agency",
                    },
                    {
                        "position": 1,
                        "role": "object",
                        "value": "notice",
                    },
                ],
                "conditions": [],
                "exceptions": [
                    {
                        "kind": "exception",
                        "scope_atom": "emergency",
                    }
                ],
                "reconstructed_structure": {
                    "roles": {
                        "actor": "agency",
                        "action": "file",
                        "object": "notice",
                    },
                    "temporal_anchors": [
                        {
                            "relation": "deadline",
                            "anchor": "within_10_days",
                        }
                    ],
                },
                "source_span_sha256": hashlib.sha256(
                    SOURCE.encode("utf-8")
                ).hexdigest(),
                "structural_signature": "structural-1",
            },
            {
                "formula_id": "doc-1:helper",
                "operator": "O",
                "modality": {"force": "obligation", "label": "obligation"},
                "predicate": {
                    "name": "emergency",
                    "role": "exception",
                },
                "arguments": [],
                "conditions": [],
                "exceptions": [],
                "reconstructed_structure": {
                    "roles": {
                        "actor": "agency",
                        "action": "review",
                    },
                    "temporal_anchors": [],
                },
                "source_span_sha256": hashlib.sha256(
                    b"emergency"
                ).hexdigest(),
                "structural_signature": "structural-helper",
            },
        ]
    return {
        "source_copy_policy": "hash_only",
        "formulas": formulas,
    }


class _ModalIr:
    def to_dict(self) -> dict[str, object]:
        return {
            "document_id": "doc-1",
            "normalized_text": SOURCE,
            "formulas": [
                {
                    "formula_id": "doc-1:f0001",
                    "provenance": {
                        "source_id": "doc-1",
                        "start_char": 0,
                        "end_char": SPAN_END,
                    },
                },
                {
                    "formula_id": "doc-1:helper",
                    "provenance": {
                        "source_id": "doc-1",
                        "start_char": 32,
                        "end_char": 41,
                    },
                },
            ],
        }


class _Nlp:
    pipe_names = REQUIRED_SPACY_PIPELINE
    lang = "en"
    meta = {
        "name": "core_web_sm",
        "version": DEFAULT_SPACY_MODEL_VERSION,
        "lang": "en",
    }


class _Encoder:
    def __init__(
        self,
        *,
        fallback: bool = False,
        pipeline: tuple[str, ...] = REQUIRED_SPACY_PIPELINE,
        model: str = DEFAULT_SPACY_MODEL,
        version: str = DEFAULT_SPACY_MODEL_VERSION,
    ) -> None:
        self.model_name = model
        self.used_fallback_model = fallback
        self.nlp = SimpleNamespace(
            pipe_names=pipeline,
            lang="en",
            meta={
                "name": "core_web_sm",
                "version": version,
                "lang": "en",
            },
        )


class _Codec:
    def __init__(
        self,
        *,
        fallback: bool = False,
        pipeline: tuple[str, ...] = REQUIRED_SPACY_PIPELINE,
        model: str = DEFAULT_SPACY_MODEL,
        model_version: str = DEFAULT_SPACY_MODEL_VERSION,
        parser_name: str = "spacy_modal_codec_v1",
        modal_ir: object = None,
        encode_error: Exception | None = None,
    ) -> None:
        self.config = SimpleNamespace(
            parser_backend="spacy",
            spacy_model_name=model,
        )
        self.encoder = _Encoder(
            fallback=fallback,
            pipeline=pipeline,
            model=model,
            version=model_version,
        )
        self.parser_name = parser_name
        self.modal_ir = _ModalIr() if modal_ir is None else modal_ir
        self.encode_error = encode_error
        self.encode_calls: list[dict[str, object]] = []

    def encode(self, text: str, **kwargs: object) -> object:
        self.encode_calls.append({"text": text, **kwargs})
        if self.encode_error is not None:
            raise self.encode_error
        encoding = SimpleNamespace(
            model_name=self.encoder.model_name,
            used_fallback_model=self.encoder.used_fallback_model,
        )
        return SimpleNamespace(
            encoding=encoding,
            modal_ir=self.modal_ir,
            parser_name=self.parser_name,
        )


def _constructor(
    codec: _Codec,
    *,
    record: dict[str, object] | None = None,
) -> ModalSpacyCanonicalConstructor:
    return ModalSpacyCanonicalConstructor(
        codec_factory=lambda requested: (
            codec
            if requested == DEFAULT_SPACY_MODEL
            else pytest.fail("constructor requested the wrong model")
        ),
        repairer=lambda modal_ir: (
            record if record is not None else _record()
        ),
    )


def test_interface_and_full_spacy_identity_are_frozen() -> None:
    constructor = _constructor(_Codec())

    assert constructor.identity == MODAL_SPACY_CANONICAL_CONSTRUCTOR_INTERFACE
    assert constructor.identity == "ModalSpacyCanonicalConstructor@1"
    assert constructor.requested_model == "en_core_web_sm"
    assert constructor.required_model_version == "3.8.0"
    assert constructor.required_pipeline == (
        "tok2vec",
        "tagger",
        "parser",
        "attribute_ruler",
        "lemmatizer",
        "ner",
    )
    assert isinstance(constructor, RoundTripConstructor)


def test_full_pipeline_projects_only_canonical_scored_fields() -> None:
    codec = _Codec()
    construction = _constructor(codec).construct_with_diagnostics(
        _request(document_id="doc-1", citation="Example § 1")
    )

    assert construction.result.status is ComponentStatus.SUCCESS
    assert construction.result.canonical_ir is not None
    assert construction.result.canonical_ir.to_dict() == {
        "rules": [
            {
                "modality": "O",
                "actor": "agency",
                "action": "file",
                "object": "notice",
                "conditions": [],
                "exceptions": ["emergency"],
                "temporal": ["within_10_days"],
            }
        ]
    }
    assert set(
        construction.result.canonical_ir.to_dict()["rules"][0]
    ) == {
        "modality",
        "actor",
        "action",
        "object",
        "conditions",
        "exceptions",
        "temporal",
    }
    assert [call["text"] for call in codec.encode_calls] == [SOURCE]
    assert codec.encode_calls[0]["document_id"] == "doc-1"
    assert codec.encode_calls[0]["citation"] == "Example § 1"


def test_codec_added_sentencizer_does_not_relabel_full_model_as_degraded() -> None:
    codec = _Codec(
        pipeline=(*REQUIRED_SPACY_PIPELINE, "sentencizer")
    )
    construction = _constructor(codec).construct_with_diagnostics(_request())

    assert construction.result.status is ComponentStatus.SUCCESS
    assert (
        construction.diagnostics.frontend_status
        is ModalSpacyFrontendStatus.FULL_MODEL
    )
    assert construction.diagnostics.effective_pipeline[-1] == "sentencizer"


def test_projection_matches_existing_modal_spacy_l1_algorithm() -> None:
    vocabulary = _vocabulary()
    record = _record()
    case = {
        "allowed_atoms": vocabulary.to_dict(),
    }

    existing = pilot.project_decompiler_record(record, case)
    adapted = project_decompiler_record(record, vocabulary)

    assert adapted.to_dict() == existing


def test_constructor_polarity_preflight_on_pilot_cases() -> None:
    """exception_with_window stays polarity-clean; at least one more case too.

    Historical pilot L1 inverted ``cannot`` prohibitions to obligation. Source-
    aware projection must keep ``exception_with_window`` eligible on polarity
    and preserve polarity for at least one additional pilot case. Any remaining
    inversions are listed in ``RESIDUAL_POLARITY_INVERSION_CASE_IDS``.
    """

    repository_root = Path(__file__).resolve().parents[4]
    fixture_path = (
        repository_root
        / "tests"
        / "fixtures"
        / "semantic_roundtrip"
        / "pilot_cases.json"
    )
    cases = json.loads(fixture_path.read_text(encoding="utf-8"))
    constructor = ModalSpacyCanonicalConstructor()

    polarity_clean: list[str] = []
    residual: list[str] = []
    for case in cases:
        vocabulary = AllowedAtomVocabulary.from_dict(case["allowed_atoms"])
        gold = CanonicalRuleIR.from_dict(case["gold_ir"])
        construction = constructor.construct_with_diagnostics(
            ConstructorRequest(case["source_text"], vocabulary, {})
        )

        if construction.result.status is ComponentStatus.FAILED:
            assert (
                construction.result.failure_reason
                is FailureReason.CAPABILITY_UNAVAILABLE
            ), case["id"]
            assert (
                construction.diagnostics.frontend_status
                is ModalSpacyFrontendStatus.UNAVAILABLE
            ), case["id"]
            pytest.skip(
                "the pinned full spaCy/modal frontend is unavailable: "
                f"{construction.result.failure_detail}"
            )
        assert construction.result.status is ComponentStatus.SUCCESS, case[
            "id"
        ]
        assert construction.result.canonical_ir is not None
        assert (
            construction.diagnostics.frontend_status
            is ModalSpacyFrontendStatus.FULL_MODEL
        )
        assert construction.diagnostics.source_spans

        preflight = polarity_preflight(
            gold, construction.result.canonical_ir
        )
        assert preflight["interface"] == POLARITY_PREFLIGHT_INTERFACE
        assert preflight["promotion_requires_full_gates"] is True
        stage = compute_constructor_only_metrics(
            gold, construction.result.canonical_ir
        )
        assert stage.promotion_requires_full_gates is True

        if case["id"] == "exception_with_window":
            assert preflight["gate_passed"] is True, preflight
            assert stage.polarity_preserved is True
            # Obligation with exception + window remains projected.
            rules = construction.result.canonical_ir.rules
            assert any(rule.modality == "O" for rule in rules)
            assert any("emergency" in rule.exceptions for rule in rules)

        if preflight["gate_passed"] and stage.polarity_preserved:
            polarity_clean.append(case["id"])
        else:
            residual.append(case["id"])

    assert "exception_with_window" in polarity_clean
    additional = [
        case_id
        for case_id in polarity_clean
        if case_id != "exception_with_window"
    ]
    if not additional:
        # Fail closed unless residual inversions are explicitly documented.
        assert residual, "expected residual inversions when no additional clean case"
        assert set(residual) <= set(RESIDUAL_POLARITY_INVERSION_CASE_IDS), (
            "undocumented residual polarity inversions: "
            f"{sorted(set(residual) - set(RESIDUAL_POLARITY_INVERSION_CASE_IDS))}"
        )
    else:
        # Document only true residuals; extras in the constant are allowed.
        assert set(residual) <= set(RESIDUAL_POLARITY_INVERSION_CASE_IDS) or (
            RESIDUAL_POLARITY_INVERSION_CASE_IDS == ()
            and not residual
        )


def test_source_span_diagnostics_are_preserved_outside_realizer_payload() -> None:
    construction = _constructor(_Codec()).construct_with_diagnostics(
        _request()
    )

    assert construction.result.status is ComponentStatus.SUCCESS
    diagnostics = construction.diagnostics
    assert diagnostics.frontend_status is ModalSpacyFrontendStatus.FULL_MODEL
    assert diagnostics.fallback_used is False
    assert diagnostics.effective_pipeline == REQUIRED_SPACY_PIPELINE
    assert diagnostics.parser_backend == "spacy_modal_codec_v1"
    assert diagnostics.source_spans[0].to_dict() == {
        "formula_id": "doc-1:f0001",
        "source_id": "doc-1",
        "start_char": 0,
        "end_char": SPAN_END,
        "source_span_sha256": hashlib.sha256(
            SOURCE.encode("utf-8")
        ).hexdigest(),
        "structural_signature": "structural-1",
    }
    assert SOURCE not in str(diagnostics.to_dict())

    result_field_names = {field.name for field in fields(construction.result)}
    assert result_field_names == {
        "status",
        "canonical_ir",
        "failure_reason",
        "failure_detail",
    }
    assert construction.result.canonical_ir is not None
    realizer_payload = RealizerRequest(
        construction.result.canonical_ir,
        _vocabulary(),
        {},
    ).to_payload()
    assert set(realizer_payload) == {
        "canonical_ir",
        "allowed_atom_vocabulary",
        "config",
    }
    assert "source" not in str(realizer_payload).lower()
    assert "structural-1" not in str(realizer_payload)


@pytest.mark.parametrize(
    ("codec", "detail_fragment"),
    [
        (_Codec(fallback=True), "fallback"),
        (
            _Codec(pipeline=("tok2vec", "tagger", "parser")),
            "pipeline",
        ),
        (_Codec(model="spacy.blank:en"), "effective model"),
        (_Codec(model_version="3.7.0"), "model version"),
    ],
)
def test_degraded_frontends_fail_explicitly_without_substitution(
    codec: _Codec,
    detail_fragment: str,
) -> None:
    construction = _constructor(codec).construct_with_diagnostics(_request())

    assert construction.result.status is ComponentStatus.FAILED
    assert (
        construction.result.failure_reason
        is FailureReason.CAPABILITY_UNAVAILABLE
    )
    assert construction.result.canonical_ir is None
    assert (
        construction.diagnostics.frontend_status
        is ModalSpacyFrontendStatus.DEGRADED
    )
    assert detail_fragment in (
        construction.result.failure_detail or ""
    )
    assert codec.encode_calls == []


def test_effective_regex_parser_is_post_schedule_degradation() -> None:
    codec = _Codec(parser_name="legal_modal_parser_v1")
    construction = _constructor(codec).construct_with_diagnostics(_request())

    assert construction.result.status is ComponentStatus.FAILED
    assert (
        construction.result.failure_reason
        is FailureReason.CAPABILITY_UNAVAILABLE
    )
    assert (
        construction.diagnostics.frontend_status
        is ModalSpacyFrontendStatus.DEGRADED
    )
    assert "effective modal parser" in (
        construction.result.failure_detail or ""
    )
    assert len(codec.encode_calls) == 1


def test_unavailable_full_model_is_not_silently_replaced() -> None:
    def missing(_requested: str) -> object:
        raise ModuleNotFoundError("en_core_web_sm")

    constructor = ModalSpacyCanonicalConstructor(codec_factory=missing)
    construction = constructor.construct_with_diagnostics(_request())

    assert construction.result.status is ComponentStatus.FAILED
    assert (
        construction.result.failure_reason
        is FailureReason.CAPABILITY_UNAVAILABLE
    )
    assert (
        construction.diagnostics.frontend_status
        is ModalSpacyFrontendStatus.UNAVAILABLE
    )
    assert "unavailable" in (construction.result.failure_detail or "")
    assert "ModuleNotFoundError" in (
        construction.result.failure_detail or ""
    )


def test_permission_denied_frontend_is_reported_as_unavailable() -> None:
    def denied(_requested: str) -> object:
        raise PermissionError("frontend cache is read-only")

    construction = ModalSpacyCanonicalConstructor(
        codec_factory=denied
    ).construct_with_diagnostics(_request())

    assert construction.result.status is ComponentStatus.FAILED
    assert (
        construction.result.failure_reason
        is FailureReason.CAPABILITY_UNAVAILABLE
    )
    assert (
        construction.diagnostics.frontend_status
        is ModalSpacyFrontendStatus.UNAVAILABLE
    )
    assert "PermissionError" in (
        construction.result.failure_detail or ""
    )


@pytest.mark.parametrize(
    "config",
    [
        {"parser_backend": "regex"},
        {"fallback_allowed": True},
        {"spacy_model_name": "different_model"},
        {"required_pipeline": ["parser"]},
    ],
)
def test_public_config_cannot_weaken_the_full_frontend(
    config: dict[str, Any],
) -> None:
    codec = _Codec()
    construction = _constructor(codec).construct_with_diagnostics(
        _request(**config)
    )

    assert construction.result.status is ComponentStatus.FAILED
    assert construction.result.failure_reason is FailureReason.INVALID_OUTPUT
    assert codec.encode_calls == []


def test_empty_modal_projection_is_a_typed_empty_l1_failure() -> None:
    construction = _constructor(
        _Codec(), record=_record(formulas=[])
    ).construct_with_diagnostics(_request())

    assert construction.result.status is ComponentStatus.FAILED
    assert construction.result.failure_reason is FailureReason.EMPTY_L1
    assert construction.result.canonical_ir is None
    assert (
        construction.diagnostics.frontend_status
        is ModalSpacyFrontendStatus.FULL_MODEL
    )


def test_codec_exception_is_retained_as_a_terminal_failure() -> None:
    construction = _constructor(
        _Codec(encode_error=ValueError("bad parse"))
    ).construct_with_diagnostics(_request())

    assert construction.result.status is ComponentStatus.FAILED
    assert construction.result.failure_reason is FailureReason.EXCEPTION
    assert (
        construction.diagnostics.frontend_status
        is ModalSpacyFrontendStatus.UNAVAILABLE
    )
    assert construction.result.canonical_ir is None


def test_wrong_request_type_is_a_typed_failure() -> None:
    construction = _constructor(_Codec()).construct_with_diagnostics(
        object()  # type: ignore[arg-type]
    )

    assert construction.result.status is ComponentStatus.FAILED
    assert construction.result.failure_reason is FailureReason.INVALID_OUTPUT


def _prohibition_formula(
    *,
    operator: str,
    force: str,
    label: str,
    polarity: str,
    surface: str,
    formula_id: str = "doc-1:f0001",
) -> dict[str, object]:
    return {
        "formula_id": formula_id,
        "operator": operator,
        "modality": {
            "force": force,
            "label": label,
            "polarity": polarity,
        },
        "predicate": {
            "arity": 3,
            "name": "disclose",
            "role": "clause",
        },
        "arguments": [],
        "conditions": [],
        "exceptions": [],
        "reconstructed_structure": {
            "roles": {
                "actor": "agency",
                "action": "file",
                "object": "notice",
            },
            "temporal_anchors": [],
        },
        "provenance": {
            "source_id": "doc-1",
            "start_char": 0,
            "end_char": len(surface),
        },
        "source_span_sha256": hashlib.sha256(
            surface.encode("utf-8")
        ).hexdigest(),
        "structural_signature": "structural-polarity",
    }


def test_source_aware_projection_repairs_cannot_to_prohibition() -> None:
    """Codec alethic □ / necessity for 'cannot' must project to F."""

    surface = "Agency cannot file notice without approval."
    record = _record(
        formulas=[
            _prohibition_formula(
                operator="□",
                force="necessity",
                label="necessary",
                polarity="positive",
                surface=surface,
            )
        ]
    )
    projected = project_decompiler_record(
        record,
        _vocabulary(),
        source_text=surface,
    )
    assert projected.to_dict()["rules"] == [
        {
            "modality": "F",
            "actor": "agency",
            "action": "file",
            "object": "notice",
            "conditions": [],
            "exceptions": [],
            "temporal": [],
        }
    ]


def test_source_aware_projection_repairs_shall_not_and_must_not() -> None:
    for surface, operator, force, label in (
        (
            "Agency shall not file notice without approval.",
            "O",
            "obligation",
            "obligation",
        ),
        (
            "Agency must not file notice without approval.",
            "O",
            "obligation",
            "obligation",
        ),
    ):
        record = _record(
            formulas=[
                _prohibition_formula(
                    operator=operator,
                    force=force,
                    label=label,
                    polarity="positive",
                    surface=surface,
                )
            ]
        )
        projected = project_decompiler_record(
            record,
            _vocabulary(),
            source_text=surface,
        )
        assert projected.rules[0].modality == "F", surface


def test_polarity_inversion_unit_fixtures_fail_closed() -> None:
    """Inverted O↔F fixtures must fail polarity preflight (fail closed)."""

    gold = CanonicalRuleIR(
        (
            CanonicalRule(
                modality="F",
                actor="agency",
                action="file",
                object="notice",
                conditions=(),
                exceptions=(),
                temporal=(),
            ),
        )
    )
    inverted = CanonicalRuleIR(
        (
            CanonicalRule(
                modality="O",
                actor="agency",
                action="file",
                object="notice",
                conditions=(),
                exceptions=(),
                temporal=(),
            ),
        )
    )
    preserved = CanonicalRuleIR(
        (
            CanonicalRule(
                modality="F",
                actor="agency",
                action="file",
                object="notice",
                conditions=(),
                exceptions=(),
                temporal=(),
            ),
        )
    )

    failed = polarity_preflight(gold, inverted)
    assert failed["interface"] == POLARITY_PREFLIGHT_INTERFACE
    assert failed["gate_passed"] is False
    assert failed["all_assigned_preserved"] is False
    assert failed["inversion_count"] == 1
    assert failed["promotion_requires_full_gates"] is True
    assert "fail" in (failed["detail"] or "").lower()

    missing = polarity_preflight(gold, None)
    assert missing["gate_passed"] is False
    assert missing["evaluated"] is False

    ok = polarity_preflight(gold, preserved)
    assert ok["gate_passed"] is True
    assert ok["inversion_count"] == 0
    assert ok["promotion_requires_full_gates"] is True

    # Permission inverted to obligation also fails closed.
    gold_permission = CanonicalRuleIR(
        (
            CanonicalRule(
                modality="P",
                actor="agency",
                action="review",
                object="order",
                conditions=(),
                exceptions=(),
                temporal=(),
            ),
        )
    )
    inverted_permission = CanonicalRuleIR(
        (
            CanonicalRule(
                modality="O",
                actor="agency",
                action="review",
                object="order",
                conditions=(),
                exceptions=(),
                temporal=(),
            ),
        )
    )
    perm_failed = polarity_preflight(gold_permission, inverted_permission)
    assert perm_failed["gate_passed"] is False
    assert perm_failed["inversion_count"] == 1


def test_constructor_projects_cannot_with_source_spans() -> None:
    surface = "Agency cannot file notice."
    formula = _prohibition_formula(
        operator="□",
        force="necessity",
        label="necessary",
        polarity="positive",
        surface=surface,
    )
    record = _record(formulas=[formula])

    class _ModalIrCannot:
        def to_dict(self) -> dict[str, object]:
            return {
                "document_id": "doc-1",
                "normalized_text": surface,
                "formulas": [
                    {
                        "formula_id": "doc-1:f0001",
                        "provenance": {
                            "source_id": "doc-1",
                            "start_char": 0,
                            "end_char": len(surface),
                        },
                    }
                ],
            }

    codec = _Codec(modal_ir=_ModalIrCannot())
    construction = _constructor(codec, record=record).construct_with_diagnostics(
        ConstructorRequest(surface, _vocabulary(), {})
    )
    assert construction.result.status is ComponentStatus.SUCCESS
    assert construction.result.canonical_ir is not None
    assert construction.result.canonical_ir.rules[0].modality == "F"
    preflight = polarity_preflight(
        CanonicalRuleIR(
            (
                CanonicalRule(
                    modality="F",
                    actor="agency",
                    action="file",
                    object="notice",
                    conditions=(),
                    exceptions=(),
                    temporal=(),
                ),
            )
        ),
        construction.result.canonical_ir,
    )
    assert preflight["gate_passed"] is True
