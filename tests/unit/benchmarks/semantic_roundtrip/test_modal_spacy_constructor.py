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
    REQUIRED_SPACY_PIPELINE,
    ModalSpacyCanonicalConstructor,
    ModalSpacyFrontendStatus,
    project_decompiler_record,
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


def test_constructor_matches_frozen_modal_spacy_l1_for_every_case() -> None:
    repository_root = Path(__file__).resolve().parents[4]
    fixture_path = (
        repository_root
        / "tests"
        / "fixtures"
        / "semantic_roundtrip"
        / "pilot_cases.json"
    )
    report_path = (
        repository_root
        / "workspace"
        / "benchmarks"
        / "semantic-logic-roundtrip"
        / "2026-07-26-audited-v2"
        / "semantic-roundtrip-report.json"
    )
    cases = json.loads(fixture_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    pilot_l1_by_case = {
        case["case_id"]: case["arms"]["modal_spacy"]["l1"]
        for case in report["cases"]
    }
    constructor = ModalSpacyCanonicalConstructor()

    for case in cases:
        vocabulary = AllowedAtomVocabulary.from_dict(case["allowed_atoms"])
        construction = constructor.construct_with_diagnostics(
            ConstructorRequest(case["source_text"], vocabulary, {})
        )

        assert construction.result.status is ComponentStatus.SUCCESS, case[
            "id"
        ]
        assert construction.result.canonical_ir is not None
        assert (
            construction.result.canonical_ir.to_dict()
            == pilot_l1_by_case[case["id"]]
        ), case["id"]
        assert (
            construction.diagnostics.frontend_status
            is ModalSpacyFrontendStatus.FULL_MODEL
        )
        assert construction.diagnostics.source_spans


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
